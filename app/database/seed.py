"""초기 시드 데이터 — 부서 및 admin 계정 생성"""

import logging

from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.database.models import Department, User

logger = logging.getLogger(__name__)

DEPARTMENTS = [
    {"name": "Front Office", "code": "FO"},
    {"name": "Food & Beverage", "code": "FB"},
    {"name": "Housekeeping", "code": "HK"},
    {"name": "Engineering", "code": "ENG"},
    {"name": "Sales & Marketing", "code": "SM"},
    {"name": "Finance", "code": "FIN"},
    {"name": "Human Resources", "code": "HR"},
    {"name": "Security", "code": "SEC"},
]


def seed(db: Session) -> None:
    # 부서
    for dept_data in DEPARTMENTS:
        exists = db.query(Department).filter_by(code=dept_data["code"]).first()
        if not exists:
            db.add(Department(**dept_data))
    db.flush()

    # Admin 계정
    admin_email = "admin@hotel.local"
    if not db.query(User).filter_by(email=admin_email).first():
        db.add(
            User(
                email=admin_email,
                password_hash=hash_password("Admin1234!"),
                name="시스템 관리자",
                role="admin",
            )
        )
    db.commit()
    logger.info("시드 데이터 초기화 완료")
