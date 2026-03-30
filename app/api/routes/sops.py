"""SOP 디지털화 REST API (SOP-F01~F32)"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser, RequireManager
from app.database.connection import get_db
from app.database.crud import get_sop, list_sops
from app.database.models import SOP
from app.models.schemas import (
    AcknowledgeStatsOut,
    SOPExtractResponse,
    SOPOut,
    SOPUpdateRequest,
)
from app.sop.export import export_checklist_csv, export_sop_to_pdf
from app.sop.service import SOPService
from app.storage.service import file_storage
from app.tasks.sop_tasks import extract_sop_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sops", tags=["SOP"])
sop_service = SOPService()

# ── 업로드 및 추출 ─────────────────────────────────────────


@router.post("/extract", response_model=SOPExtractResponse, status_code=status.HTTP_201_CREATED)
async def extract_sop(
    file: UploadFile = File(...),
    department_id: Optional[int] = Form(None),
    current_user: CurrentUser = CurrentUser,
    db: Session = Depends(get_db),
):
    """SOP 파일 업로드 → Celery 비동기 처리 enqueue → 즉시 반환 (SOP-F01, F06, F10)

    처리 흐름:
      1. 파일 저장
      2. SOP 레코드 생성 (status='processing')
      3. Celery 태스크 enqueue (OCR + AI 추출)
      4. 즉시 {sop_id, status:'processing'} 반환

    처리 완료 후 GET /sops/{sop_id}로 status 폴링 가능 (processing → draft)
    """
    allowed = {"application/pdf", "text/plain",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="PDF, DOCX, TXT 파일만 허용됩니다")

    # 파일 저장
    saved = await file_storage.save(file, subfolder="sops")
    file_type = saved["file_type"]
    file_path = str(file_storage.base_path / "sops" / saved["storage_key"].split("/")[-1])

    # SOP 레코드 생성 (processing 상태 — 즉시 DB에 저장)
    sop = SOP(
        id=str(uuid.uuid4()),
        title=file.filename or "처리중",
        status="processing",
        version="1.0",
        department_id=department_id,
        source_file=file_path,
        review_required=True,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(sop)
    db.commit()
    db.refresh(sop)

    # Celery 태스크 enqueue — 비동기 처리 (블로킹 없음)
    extract_sop_task.delay(sop.id, file_path, file_type, department_id, current_user.id)

    return SOPExtractResponse(
        sop_id=sop.id,
        title=sop.title,
        review_required=sop.review_required,
        extraction_confidence=sop.extraction_confidence,
        ocr_confidence=sop.ocr_confidence,
        status=sop.status,
    )


# ── 목록 / 단건 조회 ─────────────────────────────────────────


@router.get("", response_model=list[SOPOut])
def list_sop(
    department_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current_user: CurrentUser = CurrentUser,
    db: Session = Depends(get_db),
):
    """SOP 목록 조회 (부서/상태 필터)"""
    return list_sops(db, department_id=department_id, status=status, skip=skip, limit=limit)


@router.get("/{sop_id}", response_model=SOPOut)
def get_sop_detail(
    sop_id: str,
    current_user: CurrentUser = CurrentUser,
    db: Session = Depends(get_db),
):
    sop = _get_or_404(db, sop_id)
    return sop


# ── 수정 ─────────────────────────────────────────────────────


@router.put("/{sop_id}", response_model=SOPOut)
def update_sop(
    sop_id: str,
    body: SOPUpdateRequest,
    current_user: CurrentUser = CurrentUser,
    db: Session = Depends(get_db),
):
    """SOP 내용 수동 수정 (검토 에디터) — draft/under_review 상태만 허용"""
    sop = _get_or_404(db, sop_id)
    if sop.status not in ("draft", "under_review"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="active/archived 상태의 SOP는 수정할 수 없습니다. 신규 버전을 생성하세요.",
        )
    updates = body.model_dump(exclude_none=True)
    if "steps" in updates:
        updates["steps"] = [s if isinstance(s, dict) else s.model_dump() for s in body.steps]
    if "checklist_items" in updates:
        updates["checklist_items"] = [
            i if isinstance(i, dict) else i.model_dump() for i in body.checklist_items
        ]
    return sop_service.update(db, sop, updates, updated_by=current_user.id)


# ── 확정 ─────────────────────────────────────────────────────


@router.post("/{sop_id}/publish", response_model=SOPOut)
def publish_sop(
    sop_id: str,
    current_user: CurrentUser = CurrentUser,
    db: Session = Depends(get_db),
    _: None = RequireManager,
):
    """SOP 확정(publish): draft → active, RAG 인덱싱, 부서 알림 (SOP-F13)"""
    sop = _get_or_404(db, sop_id)
    if sop.status == "active":
        raise HTTPException(status_code=409, detail="이미 확정된 SOP입니다")
    if sop.status == "archived":
        raise HTTPException(status_code=409, detail="아카이브된 SOP는 확정할 수 없습니다")
    return sop_service.publish(db, sop, publisher_id=current_user.id)


# ── 신규 버전 ─────────────────────────────────────────────────


@router.post("/{sop_id}/versions", response_model=SOPExtractResponse, status_code=201)
async def create_new_version(
    sop_id: str,
    file: UploadFile = File(...),
    current_user: CurrentUser = CurrentUser,
    db: Session = Depends(get_db),
    _: None = RequireManager,
):
    """신규 버전 생성 — 기존 버전 이력 보관 후 재추출 (SOP-F30)"""
    sop = _get_or_404(db, sop_id)
    saved = await file_storage.save(file, subfolder="sops")
    file_type = saved["file_type"]
    file_path = str(file_storage.base_path / "sops" / saved["storage_key"].split("/")[-1])

    updated = sop_service.create_new_version(
        db, sop, file_path, file_type, updated_by=current_user.id
    )
    return SOPExtractResponse(
        sop_id=updated.id,
        title=updated.title,
        review_required=updated.review_required,
        extraction_confidence=updated.extraction_confidence,
        ocr_confidence=updated.ocr_confidence,
        status=updated.status,
    )


# ── 아카이브 ─────────────────────────────────────────────────


@router.delete("/{sop_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_sop(
    sop_id: str,
    current_user: CurrentUser = CurrentUser,
    db: Session = Depends(get_db),
    _: None = RequireManager,
):
    """SOP 아카이브 (소프트 삭제) — Manager 이상"""
    sop = _get_or_404(db, sop_id)
    sop_service.archive(db, sop, archived_by=current_user.id)


# ── Export ────────────────────────────────────────────────────


@router.get("/{sop_id}/export")
def export_sop(
    sop_id: str,
    format: str = "pdf",
    current_user: CurrentUser = CurrentUser,
    db: Session = Depends(get_db),
):
    """SOP PDF 또는 체크리스트 CSV 다운로드 (SOP-F22)"""
    sop = _get_or_404(db, sop_id)
    sop_dict = {
        "id": sop.id,
        "title": sop.title,
        "department_id": sop.department_id,
        "version": sop.version,
        "steps": sop.steps or [],
        "checklist_items": sop.checklist_items or [],
        "cautions": sop.cautions or [],
        "updated_at": sop.updated_at.isoformat() if sop.updated_at else "",
    }

    if format == "pdf":
        pdf_bytes = export_sop_to_pdf(sop_dict)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="sop_{sop_id}.pdf"'},
        )
    if format == "checklist":
        csv_str = export_checklist_csv(sop_dict)
        return Response(
            content=csv_str.encode("utf-8-sig"),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="checklist_{sop_id}.csv"'},
        )
    raise HTTPException(status_code=400, detail="format은 'pdf' 또는 'checklist'만 허용")


# ── Acknowledge ───────────────────────────────────────────────


@router.post("/{sop_id}/acknowledge", status_code=status.HTTP_201_CREATED)
def acknowledge_sop(
    sop_id: str,
    current_user: CurrentUser = CurrentUser,
    db: Session = Depends(get_db),
):
    """SOP 확인(Acknowledge) 처리 (SOP-F32)"""
    sop = _get_or_404(db, sop_id)
    if sop.status != "active":
        raise HTTPException(status_code=409, detail="active 상태의 SOP만 확인할 수 있습니다")
    ack = sop_service.acknowledge(db, sop, user_id=current_user.id)
    return {"sop_id": sop_id, "version": sop.version, "acked_at": ack.acked_at.isoformat()}


@router.get("/{sop_id}/acknowledge-stats", response_model=AcknowledgeStatsOut)
def acknowledge_stats(
    sop_id: str,
    current_user: CurrentUser = CurrentUser,
    db: Session = Depends(get_db),
    _: None = RequireManager,
):
    """부서 내 Acknowledge 완료율 조회 — Manager 이상 (SOP-F32)"""
    sop = _get_or_404(db, sop_id)
    return sop_service.get_acknowledge_stats(db, sop)


# ── 유틸 ─────────────────────────────────────────────────────


def _get_or_404(db: Session, sop_id: str) -> SOP:
    sop = get_sop(db, sop_id)
    if not sop:
        raise HTTPException(status_code=404, detail=f"SOP를 찾을 수 없습니다: {sop_id}")
    return sop
