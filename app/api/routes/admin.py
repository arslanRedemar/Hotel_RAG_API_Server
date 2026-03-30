"""Admin API — 사용자·감사로그·부하테스트 결과 관리 (Admin Panel 전용)"""

import logging
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.audit.logger import audit_log
from app.auth.dependencies import CurrentUser, RequireAdmin
from app.auth.password import hash_password
from app.database import crud
from app.database.connection import get_db

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)

_VALID_ROLES = {"admin", "manager", "staff"}


# ── 스키마 ──────────────────────────────────────────────────


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str
    department_id: int | None
    is_active: bool

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: str
    password: str
    name: str
    role: str = "staff"
    department_id: int | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in _VALID_ROLES:
            raise ValueError(f"role must be one of {_VALID_ROLES}")
        return v


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    department_id: int | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_ROLES:
            raise ValueError(f"role must be one of {_VALID_ROLES}")
        return v


class AuditLogResponse(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: str | None
    actor_id: int | None
    actor_email: str | None
    before_value: dict | None
    after_value: dict | None
    occurred_at: str

    model_config = {"from_attributes": True}


class LoadTestResultCreate(BaseModel):
    ci_run_id: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    triggered_by: str = "ci"
    test_scenario: str | None = None
    p50_ms: int | None = None
    p95_ms: int | None = None
    p99_ms: int | None = None
    avg_ms: int | None = None
    max_ms: int | None = None
    error_rate_pct: float | None = None
    req_per_sec: float | None = None
    max_vus: int | None = None
    duration_sec: int | None = None
    sla_passed: bool = True
    raw_report_url: str | None = None


class LoadTestResultResponse(BaseModel):
    id: int
    ci_run_id: str | None
    branch: str | None
    commit_sha: str | None
    triggered_by: str
    test_scenario: str | None
    p50_ms: int | None
    p95_ms: int | None
    p99_ms: int | None
    avg_ms: int | None
    max_ms: int | None
    error_rate_pct: float | None
    req_per_sec: float | None
    max_vus: int | None
    duration_sec: int | None
    sla_passed: bool
    raw_report_url: str | None
    created_at: str  # ISO 8601

    model_config = {"from_attributes": True}


# ── 사용자 관리 ──────────────────────────────────────────────


@router.get("/users", dependencies=[RequireAdmin])
def list_users(
    role: str | None = None,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    users = crud.list_users(db, role=role, is_active=is_active, skip=skip, limit=limit)
    return {"users": [UserResponse.model_validate(u) for u in users]}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    request: Request,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    _: None = RequireAdmin,
):
    if crud.get_user_by_email(db, data.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 존재하는 이메일입니다.")

    user = crud.create_user(
        db,
        email=data.email,
        password_hash=hash_password(data.password),
        name=data.name,
        role=data.role,
        department_id=data.department_id,
    )

    audit_log.log(
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        actor_id=current_user.id,
        actor_email=current_user.email,
        ip_address=request.client.host if request.client else None,
        after_value={"email": user.email, "role": user.role},
    )
    logger.info("관리자 %s가 사용자 %s 생성", current_user.email, user.email)
    return UserResponse.model_validate(user)


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    data: UserUpdate,
    request: Request,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    _: None = RequireAdmin,
):
    existing = crud.get_user(db, user_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자를 찾을 수 없습니다.")

    before = {"role": existing.role, "is_active": existing.is_active}
    update_kwargs = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    user = crud.update_user(db, user_id, **update_kwargs)

    audit_log.log(
        action="user.update",
        entity_type="user",
        entity_id=user_id,
        actor_id=current_user.id,
        actor_email=current_user.email,
        ip_address=request.client.host if request.client else None,
        before_value=before,
        after_value=update_kwargs,
    )
    return UserResponse.model_validate(user)


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    request: Request,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    _: None = RequireAdmin,
):
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자를 찾을 수 없습니다.")

    alphabet = string.ascii_letters + string.digits
    temp_pw = "".join(secrets.choice(alphabet) for _ in range(12))
    crud.update_user(db, user_id, password_hash=hash_password(temp_pw))

    audit_log.log(
        action="user.reset_password",
        entity_type="user",
        entity_id=user_id,
        actor_id=current_user.id,
        actor_email=current_user.email,
        ip_address=request.client.host if request.client else None,
    )
    logger.info("관리자 %s가 사용자 %d 비밀번호 재설정", current_user.email, user_id)
    return {"message": "임시 비밀번호가 발급되었습니다. 이메일 발송은 알림 모듈 연동 후 활성화됩니다."}


# ── 감사 로그 ────────────────────────────────────────────────


@router.get("/audit-logs", dependencies=[RequireAdmin])
def list_audit_logs(
    action: str | None = None,
    entity_type: str | None = None,
    actor_id: int | None = None,
    limit: int = 50,
    skip: int = 0,
    db: Session = Depends(get_db),
):
    logs = crud.list_audit_logs(
        db,
        action=action,
        entity_type=entity_type,
        actor_id=actor_id,
        limit=limit,
        skip=skip,
    )
    return {
        "logs": [
            {
                "id": log.id,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "actor_id": log.actor_id,
                "actor_email": log.actor_email,
                "before_value": log.before_value,
                "after_value": log.after_value,
                "occurred_at": log.occurred_at.isoformat(),
            }
            for log in logs
        ]
    }


# ── 부하 테스트 결과 ─────────────────────────────────────────


def _serialize_load_test(r) -> LoadTestResultResponse:
    return LoadTestResultResponse(
        id=r.id,
        ci_run_id=r.ci_run_id,
        branch=r.branch,
        commit_sha=r.commit_sha,
        triggered_by=r.triggered_by,
        test_scenario=r.test_scenario,
        p50_ms=r.p50_ms,
        p95_ms=r.p95_ms,
        p99_ms=r.p99_ms,
        avg_ms=r.avg_ms,
        max_ms=r.max_ms,
        error_rate_pct=float(r.error_rate_pct) if r.error_rate_pct is not None else None,
        req_per_sec=float(r.req_per_sec) if r.req_per_sec is not None else None,
        max_vus=r.max_vus,
        duration_sec=r.duration_sec,
        sla_passed=r.sla_passed,
        raw_report_url=r.raw_report_url,
        created_at=r.created_at.isoformat(),
    )


@router.post("/load-test-results", status_code=status.HTTP_201_CREATED)
def save_load_test_result(
    data: LoadTestResultCreate,
    db: Session = Depends(get_db),
    _: None = RequireAdmin,
):
    result = crud.create_load_test_result(db, **data.model_dump())
    return _serialize_load_test(result)


@router.get("/load-test-results", dependencies=[RequireAdmin])
def list_load_test_results(
    limit: int = 20,
    skip: int = 0,
    db: Session = Depends(get_db),
):
    results = crud.list_load_test_results(db, limit=limit, skip=skip)
    return {"results": [_serialize_load_test(r) for r in results]}


# ── 알림 이력 (SYS-F12) ─────────────────────────────────────


@router.get("/notification-logs", dependencies=[RequireAdmin])
def list_notification_logs(
    channel: str | None = None,
    user_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    skip: int = 0,
    db: Session = Depends(get_db),
):
    """알림 발송 이력 목록 조회 (SYS-F12)"""
    from app.database.models import NotificationLog

    q = db.query(NotificationLog)
    if channel:
        q = q.filter(NotificationLog.channel == channel)
    if user_id:
        q = q.filter(NotificationLog.user_id == user_id)
    if status:
        q = q.filter(NotificationLog.status == status)
    logs = q.order_by(NotificationLog.created_at.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": log.id,
            "user_id": log.user_id,
            "channel": log.channel,
            "subject": log.subject,
            "body": log.body,
            "recipient_email": log.recipient_email,
            "status": log.status,
            "error_message": log.error_message,
            "sent_at": log.sent_at.isoformat() if log.sent_at else None,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
