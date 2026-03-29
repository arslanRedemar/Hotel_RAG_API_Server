from sqlalchemy.orm import Session

from app.database.models import SOP, AuditLog, ChatMessage, ChatSession, LoadTestResult, User


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


# ── SOP CRUD ─────────────────────────────────────────────────


def get_sop(db: Session, sop_id: str) -> SOP | None:
    return db.get(SOP, sop_id)


def list_sops(
    db: Session,
    department_id: int | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[SOP]:
    q = db.query(SOP)
    if department_id is not None:
        q = q.filter(SOP.department_id == department_id)
    if status:
        q = q.filter(SOP.status == status)
    return q.order_by(SOP.created_at.desc()).offset(skip).limit(limit).all()


# ── Admin: 사용자 관리 ────────────────────────────────────────


def list_users(
    db: Session,
    role: str | None = None,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[User]:
    q = db.query(User)
    if role is not None:
        q = q.filter(User.role == role)
    if is_active is not None:
        q = q.filter(User.is_active == is_active)
    return q.order_by(User.created_at.desc()).offset(skip).limit(limit).all()


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def create_user(
    db: Session,
    email: str,
    password_hash: str,
    name: str,
    role: str = "staff",
    department_id: int | None = None,
) -> User:
    user = User(
        email=email,
        password_hash=password_hash,
        name=name,
        role=role,
        department_id=department_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    user_id: int,
    **kwargs,
) -> User | None:
    user = db.get(User, user_id)
    if not user:
        return None
    for key, value in kwargs.items():
        if hasattr(user, key):
            setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user


# ── Admin: 감사 로그 ─────────────────────────────────────────


def list_audit_logs(
    db: Session,
    action: str | None = None,
    entity_type: str | None = None,
    actor_id: int | None = None,
    limit: int = 50,
    skip: int = 0,
) -> list[AuditLog]:
    q = db.query(AuditLog)
    if action is not None:
        q = q.filter(AuditLog.action == action)
    if entity_type is not None:
        q = q.filter(AuditLog.entity_type == entity_type)
    if actor_id is not None:
        q = q.filter(AuditLog.actor_id == actor_id)
    return q.order_by(AuditLog.occurred_at.desc()).offset(skip).limit(limit).all()


# ── Admin: 부하 테스트 결과 ──────────────────────────────────


def create_load_test_result(db: Session, **kwargs) -> LoadTestResult:
    result = LoadTestResult(**kwargs)
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def list_load_test_results(
    db: Session,
    limit: int = 20,
    skip: int = 0,
) -> list[LoadTestResult]:
    return (
        db.query(LoadTestResult)
        .order_by(LoadTestResult.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
