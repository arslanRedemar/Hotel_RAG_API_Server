"""FastAPI 의존성 주입 — 인증 및 권한 검사"""

import logging
from typing import Annotated

import redis as redis_lib
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.auth.jwt import verify_access_token
from app.core.config import settings
from app.database.connection import get_db
from app.database.models import User

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=True)

# Redis 클라이언트 (Refresh Token 블랙리스트)
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

BLACKLIST_PREFIX = "blacklist:refresh:"


def is_token_blacklisted(jti: str) -> bool:
    return bool(_redis.exists(f"{BLACKLIST_PREFIX}{jti}"))


def blacklist_token(jti: str, ttl_seconds: int) -> None:
    _redis.setex(f"{BLACKLIST_PREFIX}{jti}", ttl_seconds, "1")


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    try:
        payload = verify_access_token(token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"유효하지 않은 토큰: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = int(payload["sub"])
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없거나 비활성 상태입니다",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str):
    """특정 역할 이상만 허용하는 의존성 팩토리."""

    def checker(current_user: CurrentUser) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"권한이 없습니다. 필요 역할: {roles}",
            )
        return current_user

    return checker


RequireAdmin = Depends(require_role("admin"))
RequireManager = Depends(require_role("admin", "manager"))
