"""채팅 API — 인증 + 소스 디테일 + 부서 필터 (RAG-F11/F13/F20)"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.connection import get_db
from app.database.crud import save_message
from app.database.models import User
from app.models.schemas import ChatRequest, ChatResponse, SourceDocument
from app.rag.chain import chat as rag_chat

router = APIRouter(prefix="/chat", tags=["Chat"])


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

    # 하위 호환: sources (파일명 목록)
    sources = list({
        sd.source for sd in source_details if sd.source
    })

    # RAG-F11: 상세 소스 정보
    source_documents = [
        SourceDocument(
            source=sd.source,
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
