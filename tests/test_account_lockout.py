"""SYS-F06: 계정 잠금 (5회 연속 실패 시 30분 잠금) 테스트"""

from datetime import datetime, timedelta

import pytest

from app.auth.password import hash_password
from app.database.models import Department, User


# ── 픽스처 ────────────────────────────────────────────────────

@pytest.fixture
def lockout_dept(db):
    dept = db.query(Department).filter_by(code="LOCK_TEST").first()
    if not dept:
        dept = Department(name="잠금테스트부서", code="LOCK_TEST")
        db.add(dept)
        db.commit()
        db.refresh(dept)
    return dept


@pytest.fixture
def lockout_user(db, lockout_dept):
    user = db.query(User).filter_by(email="locktest@hotel.local").first()
    if not user:
        user = User(
            email="locktest@hotel.local",
            password_hash=hash_password("Correct1234!"),
            name="잠금테스트유저",
            role="staff",
            department_id=lockout_dept.id,
            is_active=True,
            failed_login_attempts=0,
            locked_until=None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()
    return user


# ── 단위 테스트: 잠금 로직 ────────────────────────────────────

class TestAccountLockoutLogic:
    def test_failed_attempts_increment(self, db, lockout_user):
        """로그인 실패 시 failed_login_attempts 증가"""
        from app.auth.lockout import record_failed_login
        record_failed_login(db, lockout_user)
        db.refresh(lockout_user)
        assert lockout_user.failed_login_attempts == 1

    def test_account_locked_after_5_failures(self, db, lockout_user):
        """5회 실패 시 locked_until 설정"""
        from app.auth.lockout import record_failed_login, is_account_locked
        for _ in range(5):
            record_failed_login(db, lockout_user)
        db.refresh(lockout_user)
        assert lockout_user.failed_login_attempts == 5
        assert lockout_user.locked_until is not None
        assert is_account_locked(lockout_user) is True

    def test_account_not_locked_before_5_failures(self, db, lockout_user):
        """4회 실패는 잠금 안 됨"""
        from app.auth.lockout import record_failed_login, is_account_locked
        for _ in range(4):
            record_failed_login(db, lockout_user)
        db.refresh(lockout_user)
        assert is_account_locked(lockout_user) is False

    def test_lockout_expires_after_30_minutes(self, db, lockout_user):
        """locked_until이 과거이면 잠금 해제됨"""
        from app.auth.lockout import is_account_locked
        lockout_user.locked_until = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        assert is_account_locked(lockout_user) is False

    def test_reset_on_successful_login(self, db, lockout_user):
        """로그인 성공 시 실패 횟수 초기화"""
        from app.auth.lockout import record_failed_login, reset_failed_login
        for _ in range(3):
            record_failed_login(db, lockout_user)
        reset_failed_login(db, lockout_user)
        db.refresh(lockout_user)
        assert lockout_user.failed_login_attempts == 0
        assert lockout_user.locked_until is None


# ── 통합 테스트: API 레벨 ─────────────────────────────────────

class TestAccountLockoutAPI:
    def test_successful_login_resets_counter(self, client, db, lockout_user):
        """정상 로그인 후 실패 카운터 리셋"""
        lockout_user.failed_login_attempts = 2
        db.commit()

        r = client.post("/api/v1/auth/login", json={
            "email": "locktest@hotel.local",
            "password": "Correct1234!",
        })
        assert r.status_code == 200
        db.refresh(lockout_user)
        assert lockout_user.failed_login_attempts == 0

    def test_wrong_password_increments_counter(self, client, db, lockout_user):
        """틀린 비밀번호 → 카운터 증가"""
        before = lockout_user.failed_login_attempts
        r = client.post("/api/v1/auth/login", json={
            "email": "locktest@hotel.local",
            "password": "WrongPassword!",
        })
        assert r.status_code == 401
        db.refresh(lockout_user)
        assert lockout_user.failed_login_attempts == before + 1

    def test_5_failures_returns_locked_message(self, client, db, lockout_user):
        """5회 실패 시 계정 잠금 메시지 반환"""
        lockout_user.failed_login_attempts = 4
        db.commit()

        r = client.post("/api/v1/auth/login", json={
            "email": "locktest@hotel.local",
            "password": "WrongPassword!",
        })
        assert r.status_code == 423
        assert "잠금" in r.json()["detail"]

    def test_locked_account_rejects_correct_password(self, client, db, lockout_user):
        """잠긴 계정은 올바른 비밀번호도 거부"""
        lockout_user.failed_login_attempts = 5
        lockout_user.locked_until = datetime.utcnow() + timedelta(minutes=29)
        db.commit()

        r = client.post("/api/v1/auth/login", json={
            "email": "locktest@hotel.local",
            "password": "Correct1234!",
        })
        assert r.status_code == 423
        assert "잠금" in r.json()["detail"]

    def test_expired_lock_allows_login(self, client, db, lockout_user):
        """잠금 만료 후 정상 로그인 가능"""
        lockout_user.failed_login_attempts = 5
        lockout_user.locked_until = datetime.utcnow() - timedelta(minutes=1)
        db.commit()

        r = client.post("/api/v1/auth/login", json={
            "email": "locktest@hotel.local",
            "password": "Correct1234!",
        })
        assert r.status_code == 200
