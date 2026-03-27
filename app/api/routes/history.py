from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.models.schemas import HistoryResponse
from app.database.connection import get_db
from app.database.crud import get_history, delete_session

router = APIRouter(prefix="/history", tags=["History"])


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
