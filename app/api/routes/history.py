from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.connection import get_db
from app.database.crud import get_history, delete_session
from app.database.models import ChatMessage, ChatSession, User
from app.models.schemas import HistoryResponse

router = APIRouter(prefix="/history", tags=["History"])


@router.get("/sessions")
def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """세션 목록 (최신순, 각 세션의 마지막 메시지 포함) — Phase 4 사이드바용"""
    sessions = (
        db.query(ChatSession)
        .order_by(ChatSession.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for s in sessions:
        latest = (
            db.query(ChatMessage)
            .filter_by(session_id=s.session_id)
            .order_by(ChatMessage.created_at.desc())
            .first()
        )
        result.append({
            "session_id": s.session_id,
            "created_at": s.created_at.isoformat(),
            "last_message": latest.content[:80] if latest else None,
            "last_role": latest.role if latest else None,
        })
    return result


@router.get("/{session_id}", response_model=HistoryResponse)
def get_chat_history(session_id: str, db: Session = Depends(get_db)):
    messages = get_history(db, session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    return HistoryResponse(session_id=session_id, messages=messages)


@router.delete("/{session_id}", status_code=204)
def delete_chat_history(session_id: str, db: Session = Depends(get_db)):
    if not delete_session(db, session_id):
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
