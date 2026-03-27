from sqlalchemy.orm import Session

from app.database.models import ChatSession, ChatMessage


def get_or_create_session(db: Session, session_id: str) -> ChatSession:
    session = db.query(ChatSession).filter_by(session_id=session_id).first()
    if not session:
        session = ChatSession(session_id=session_id)
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def save_message(
    db: Session,
    session_id: str,
    role: str,
    content: str,
    sources: list[str] | None = None,
) -> ChatMessage:
    get_or_create_session(db, session_id)
    msg = ChatMessage(session_id=session_id, role=role, content=content, sources=sources)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_history(db: Session, session_id: str) -> list[ChatMessage]:
    return (
        db.query(ChatMessage)
        .filter_by(session_id=session_id)
        .order_by(ChatMessage.created_at)
        .all()
    )


def delete_session(db: Session, session_id: str) -> bool:
    session = db.query(ChatSession).filter_by(session_id=session_id).first()
    if not session:
        return False
    db.delete(session)
    db.commit()
    return True
