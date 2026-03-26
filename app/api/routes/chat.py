import uuid
from fastapi import APIRouter, HTTPException

from app.models.schemas import ChatRequest, ChatResponse
from app.rag.chain import chat as rag_chat

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
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

    return ChatResponse(
        answer=answer,
        sources=sources,
        session_id=session_id,
    )
