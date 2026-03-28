from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session

from app.core.config import settings

_url = settings.mysql_url
_is_sqlite = _url.startswith("sqlite")

engine = create_engine(
    _url,
    **(
        {}
        if _is_sqlite
        else {
            "pool_pre_ping": True,
            "pool_recycle": 3600,
            "pool_size": 10,
            "max_overflow": 20,
        }
    ),
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 의존성 주입용 DB 세션 생성기."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_audit_db() -> Session:
    """감사 로그 전용 세션 (컨텍스트 매니저)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """앱 시작 시 테이블을 생성합니다 (없을 경우에만)."""
    from app.database import models  # noqa: F401 — 모델 등록
    Base.metadata.create_all(bind=engine)


def check_db_connection() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
