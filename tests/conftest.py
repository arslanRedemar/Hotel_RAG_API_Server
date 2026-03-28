"""공용 pytest 픽스처"""

import os

# 반드시 앱 임포트 전에 설정
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ["MYSQL_URL"] = "sqlite:///:memory:"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.connection import Base, get_db
from app.database.models import Department, User
from app.auth.password import hash_password

# ── 인메모리 SQLite 엔진 (테스트 전용) ──────────────────────

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# SQLite에서 ENUM 등 MySQL 전용 타입 무시되도록 설정
@event.listens_for(TEST_ENGINE, "connect")
def set_sqlite_pragma(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA foreign_keys=ON")

TestingSessionLocal = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


@pytest.fixture(scope="session", autouse=True)
def create_test_tables():
    # 앱 내 엔진을 테스트 엔진으로 교체
    import app.database.connection as conn_module
    conn_module.engine = TEST_ENGINE
    conn_module.SessionLocal = TestingSessionLocal

    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def db(create_test_tables):
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db):
    from main import app

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def test_dept(db):
    dept = db.query(Department).filter_by(code="FRONT").first()
    if not dept:
        dept = Department(name="프런트 오피스", code="FRONT")
        db.add(dept)
        db.commit()
        db.refresh(dept)
    return dept


@pytest.fixture
def staff_user(db, test_dept):
    user = db.query(User).filter_by(email="staff@hotel.com").first()
    if not user:
        user = User(
            email="staff@hotel.com",
            password_hash=hash_password("pass1234"),
            name="직원A",
            role="staff",
            department_id=test_dept.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@pytest.fixture
def manager_user(db, test_dept):
    user = db.query(User).filter_by(email="manager@hotel.com").first()
    if not user:
        user = User(
            email="manager@hotel.com",
            password_hash=hash_password("pass1234"),
            name="매니저B",
            role="manager",
            department_id=test_dept.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@pytest.fixture
def staff_token(client, staff_user):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "staff@hotel.com", "password": "pass1234"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
def manager_token(client, manager_user):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "manager@hotel.com", "password": "pass1234"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]
