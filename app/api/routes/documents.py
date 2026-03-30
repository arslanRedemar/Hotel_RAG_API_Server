"""문서 관리 API — 업로드/목록/버전관리/삭제 (RAG-F01~04, F30~32)"""

import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_role
from app.core.config import settings
from app.database.connection import get_db
from app.database.models import Document as DocModel, DocumentVersion, User
from app.models.schemas import DocumentOut, DocumentUploadResponse
from app.notifications.service import notify
from app.rag.ingest import delete_document_chunks, ingest_documents

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])

ALLOWED_EXTENSIONS = {"pdf", "txt", "docx"}


def _save_upload_file(upload_file: UploadFile, sub_dir: str = "docs") -> str:
    """업로드 파일을 로컬 스토리지에 저장하고 경로 반환"""
    storage_dir = Path(settings.file_storage_path) / sub_dir
    storage_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(upload_file.filename or "file").suffix.lower().lstrip(".")
    unique_name = f"{uuid.uuid4()}.{ext}"
    file_path = storage_dir / unique_name

    content = upload_file.file.read()
    file_path.write_bytes(content)
    return str(file_path)


def _ext_of(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


# ── POST /api/v1/documents ────────────────────────────────────

@router.post("", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    department_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """RAG-F01/02/04: 문서 업로드 → 인덱싱 → DB 저장"""
    ext = _ext_of(file.filename or "")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식입니다. 허용: {ALLOWED_EXTENSIONS}",
        )

    # 파일 저장
    saved_path = _save_upload_file(file)

    # ChromaDB 인덱싱
    try:
        ingest_result = ingest_documents(
            docs_dir=str(Path(saved_path).parent),
            department_id=department_id,
            uploaded_by=current_user.id,
        )
    except Exception as exc:
        logger.error("인덱싱 실패: %s", exc)
        ingest_result = {"chunk_count": 0, "elapsed_ms": 0}

    # DB에 문서 메타데이터 저장
    doc = DocModel(
        title=title,
        file_type=ext,
        storage_key=saved_path,
        department_id=department_id,
        uploaded_by=current_user.id,
        version=1,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 첫 버전 이력 저장
    db.add(DocumentVersion(
        document_id=doc.id,
        version=1,
        storage_key=saved_path,
        uploaded_by=current_user.id,
    ))
    db.commit()

    return DocumentUploadResponse(
        id=doc.id,
        title=doc.title,
        file_type=doc.file_type,
        chunk_count=ingest_result["chunk_count"],
        elapsed_ms=ingest_result["elapsed_ms"],
        department_id=doc.department_id,
        version=doc.version,
    )


# ── GET /api/v1/documents ─────────────────────────────────────

@router.get("", response_model=list[DocumentOut])
def list_documents(
    department_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """문서 목록 조회 (부서 필터 가능)"""
    q = db.query(DocModel).filter(DocModel.is_deleted.is_(False))
    if department_id is not None:
        q = q.filter(DocModel.department_id == department_id)
    return q.order_by(DocModel.created_at.desc()).offset(skip).limit(limit).all()


# ── GET /api/v1/documents/{id} ────────────────────────────────

@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.get(DocModel, doc_id)
    if not doc or doc.is_deleted:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return doc


# ── DELETE /api/v1/documents/{id} ────────────────────────────

@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """소프트 삭제 + 벡터 DB 청크 제거"""
    doc = db.get(DocModel, doc_id)
    if not doc or doc.is_deleted:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

    delete_document_chunks(str(doc_id))
    doc.is_deleted = True
    db.commit()


# ── POST /api/v1/documents/{id}/versions ─────────────────────

@router.post("/{doc_id}/versions", response_model=DocumentOut)
async def upload_new_version(
    doc_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager", "admin")),
):
    """RAG-F03/F30: 기존 청크 삭제 후 신규 버전 인덱싱"""
    doc = db.get(DocModel, doc_id)
    if not doc or doc.is_deleted:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

    ext = _ext_of(file.filename or "")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다.")

    # 기존 청크 삭제 (RAG-F03)
    delete_document_chunks(str(doc_id))

    # 새 파일 저장
    saved_path = _save_upload_file(file)
    new_version = doc.version + 1

    # 재인덱싱
    try:
        ingest_documents(
            docs_dir=str(Path(saved_path).parent),
            department_id=doc.department_id,
            uploaded_by=current_user.id,
            version=str(new_version),
        )
    except Exception as exc:
        logger.error("신규 버전 인덱싱 실패: %s", exc)

    # 버전 이력 저장
    db.add(DocumentVersion(
        document_id=doc.id,
        version=new_version,
        storage_key=saved_path,
        uploaded_by=current_user.id,
    ))

    doc.version = new_version
    doc.storage_key = saved_path
    db.commit()
    db.refresh(doc)

    # RAG-F32: 부서 사용자에게 문서 버전 변경 알림 발송
    await _notify_version_update(doc, new_version, db)

    return doc


async def _notify_version_update(doc, new_version: int, db) -> None:
    """부서 소속 활성 사용자들에게 신규 버전 이메일 알림"""
    try:
        dept_users = (
            db.query(User)
            .filter(User.department_id == doc.department_id, User.is_active.is_(True))
            .all()
        )
        for user in dept_users:
            await notify(
                channel="email",
                recipient=user.email,
                subject=f"[문서 업데이트] {doc.title} v{new_version} 게시됨",
                body=(
                    f"안녕하세요 {user.name}님,\n\n"
                    f"'{doc.title}' 문서의 신규 버전(v{new_version})이 등록되었습니다.\n"
                    "최신 내용을 확인해 주세요."
                ),
                user_id=user.id,
                db=db,
            )
    except Exception as exc:
        logger.warning("버전 변경 알림 발송 실패: %s", exc)
