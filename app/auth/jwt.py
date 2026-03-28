"""JWT Access / Refresh Token 생성 및 검증"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"

TokenType = Literal["access", "refresh"]


def _create_token(data: dict, token_type: TokenType) -> str:
    if token_type == "access":
        delta = timedelta(minutes=settings.access_token_expire_minutes)
    else:
        delta = timedelta(days=settings.refresh_token_expire_days)

    payload = data.copy()
    payload.update(
        {
            "type": token_type,
            "exp": datetime.now(timezone.utc) + delta,
            "iat": datetime.now(timezone.utc),
        }
    )
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(user_id: int, email: str, role: str) -> str:
    return _create_token(
        {"sub": str(user_id), "email": email, "role": role},
        "access",
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token({"sub": str(user_id)}, "refresh")


def decode_token(token: str) -> dict:
    """토큰 디코딩. 만료·서명 오류 시 JWTError 발생."""
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


def verify_access_token(token: str) -> dict:
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise JWTError("access token이 아닙니다")
    return payload


def verify_refresh_token(token: str) -> dict:
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise JWTError("refresh token이 아닙니다")
    return payload
