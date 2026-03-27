import uuid
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.models.schemas import ChatRequest, ChatResponse
from app.rag.chain import chat as rag_chat
from app.database.connection import get_db
from app.database.crud import save_message

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = Depends(get_db)):
    session_id = request.session_id or str(uuid.uuid4())

    try:
        answer, source_docs = rag_chat(session_id, request.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    sources = list({
        doc.metadata.get("source", "")
        for doc in source_docs
        if doc.metadata.get("source")
    })

    # MySQL에 대화 내역 저장
    save_message(db, session_id, role="human", content=request.message)
    save_message(db, session_id, role="ai", content=answer, sources=sources)

    return ChatResponse(answer=answer, sources=sources, session_id=session_id)
