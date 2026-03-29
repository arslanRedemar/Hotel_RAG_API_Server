"""채팅 API — 인증 + 소스 디테일 + 부서 필터 (RAG-F11/F13/F20)"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.connection import get_db
from app.database.crud import save_message
from app.database.models import SOP, User
from app.models.schemas import ChatRequest, ChatResponse, SourceDocument
from app.rag.chain import chat as rag_chat

router = APIRouter(prefix="/chat", tags=["Chat"])


def _resolve_display_names(source_details, db: Session) -> dict[str, str]:
    """source → display_name 매핑 반환.

    - sop/{uuid} 형식: DB에서 실제 SOP 제목 조회
    - 파일 경로: 파일명 stem 사용
    """
    mapping: dict[str, str] = {}
    sop_ids = [
        sd.source[4:]
        for sd in source_details
        if sd.source.startswith("sop/")
    ]

    _PLACEHOLDER = {"분할 추출 문서", "처리중", ""}

    sop_titles: dict[str, str] = {}
    if sop_ids:
        rows = db.query(SOP.id, SOP.title).filter(SOP.id.in_(sop_ids)).all()
        sop_titles = {str(row.id): row.title for row in rows}

    for sd in source_details:
        src = sd.source
        if not src:
            mapping[src] = "문서"
        elif src.startswith("sop/"):
            sop_id = src[4:]
            title = sop_titles.get(sop_id, "")
            # DB 제목이 placeholder이면 short-id로 표시
            if not title or title in _PLACEHOLDER:
                title = f"SOP ({sop_id[:8]}...)"
            mapping[src] = title
        else:
            mapping[src] = Path(src).stem or src

    return mapping


@router.post("", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session_id = request.session_id or str(uuid.uuid4())

    try:
        answer, source_details = rag_chat(
            session_id,
            request.message,
            department_ids=request.department_ids,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # SOP 제목 DB 조회로 display_name 확정
    display_map = _resolve_display_names(source_details, db)

    # 하위 호환: sources — display_name 기준으로 중복 제거
    seen_sources: set[str] = set()
    sources: list[str] = []
    for sd in source_details:
        name = display_map.get(sd.source, sd.source)
        if name not in seen_sources:
            seen_sources.add(name)
            sources.append(name)

    # RAG-F11: 상세 소스 정보
    source_documents = [
        SourceDocument(
            source=sd.source,
            display_name=display_map.get(sd.source, sd.display_name),
            page=sd.page,
            section=sd.section,
            chunk_preview=sd.chunk_preview,
            doc_type=sd.doc_type,
            department_id=sd.department_id,
        )
        for sd in source_details
    ]

    save_message(db, session_id, role="human", content=request.message)
    save_message(db, session_id, role="ai", content=answer, sources=sources)

    return ChatResponse(
        answer=answer,
        sources=sources,
        source_documents=source_documents,
        session_id=session_id,
    )
