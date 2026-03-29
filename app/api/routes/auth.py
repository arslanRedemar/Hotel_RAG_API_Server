"""인증 API — /auth"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.logger import audit_log
from app.auth.dependencies import (
    CurrentUser,
    blacklist_token,
)
from app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
)
from app.auth.password import verify_password
from app.database.connection import get_db
from app.database.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


# ── 스키마 ──────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str
    department_id: int | None

    class Config:
        from_attributes = True


# ── 엔드포인트 ───────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=body.email, is_active=True).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다",
        )

    access = create_access_token(user.id, user.email, user.role)
    refresh = create_refresh_token(user.id)

    audit_log.log(
        action="LOGIN",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        actor_email=user.email,
        ip_address=request.client.host if request.client else None,
    )

    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    try:
        payload = verify_refresh_token(body.refresh_token)
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    user_id = int(payload["sub"])
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="사용자 없음")

    # 구 Refresh Token 블랙리스트 (Rotation)
    exp: int = payload.get("exp", 0)
    ttl = max(0, exp - int(datetime.now(timezone.utc).timestamp()))
    jti = body.refresh_token[-16:]  # 마지막 16자를 식별자로 사용
    blacklist_token(jti, ttl)

    new_access = create_access_token(user.id, user.email, user.role)
    new_refresh = create_refresh_token(user.id)
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest):
    try:
        payload = verify_refresh_token(body.refresh_token)
        exp: int = payload.get("exp", 0)
        ttl = max(0, exp - int(datetime.now(timezone.utc).timestamp()))
        jti = body.refresh_token[-16:]
        blacklist_token(jti, ttl)
    except JWTError:
        pass  # 이미 만료된 토큰도 정상 처리


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser):
    return current_user
