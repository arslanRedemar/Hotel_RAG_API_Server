"""bcrypt 패스워드 해싱 (bcrypt 직접 사용 — passlib/Python 3.13 호환)"""

import bcrypt


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())
