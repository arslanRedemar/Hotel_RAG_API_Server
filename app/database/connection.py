from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session

from app.core.config import settings

engine = create_engine(
    settings.mysql_url,
    pool_pre_ping=True,   # 연결 끊김 자동 감지
    pool_recycle=3600,    # 1시간마다 커넥션 재사용
    pool_size=10,
    max_overflow=20,
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
