"""SYS-F06: 계정 잠금 — 5회 연속 실패 시 30분 잠금"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

LOCKOUT_THRESHOLD = 5       # 최대 실패 횟수
LOCKOUT_DURATION_MIN = 30   # 잠금 지속 시간 (분)


def is_account_locked(user) -> bool:
    """계정이 현재 잠금 상태인지 확인"""
    if user.locked_until is None:
        return False
    return datetime.utcnow() < user.locked_until


def record_failed_login(db: Session, user) -> None:
    """로그인 실패 기록 — 임계값 도달 시 계정 잠금"""
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= LOCKOUT_THRESHOLD:
        user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MIN)
    db.commit()


def reset_failed_login(db: Session, user) -> None:
    """로그인 성공 시 실패 횟수 초기화"""
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
