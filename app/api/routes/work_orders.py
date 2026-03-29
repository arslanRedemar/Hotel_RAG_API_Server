"""Work Order API 엔드포인트 (WO-F01, F13, F20, F30, F31, F41, F42)"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.connection import get_db
from app.database.models import User
from app.work_order.service import VALID_STATUSES, WorkOrderService

router = APIRouter(prefix="/work-orders", tags=["Work Orders"])
logger = logging.getLogger(__name__)


# ── 요청 / 응답 스키마 ────────────────────────────────────────


class WorkOrderCreate(BaseModel):
    description: str
    room_no: Optional[str] = None
    location: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    photo_urls: Optional[list[str]] = None


class StatusUpdate(BaseModel):
    status: str
    note: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"유효하지 않은 상태: {v}")
        return v


class CompleteRequest(BaseModel):
    resolution_note: str
    actual_duration_min: int
    parts_used: Optional[list[dict]] = None


class CategoryUpdate(BaseModel):
    category: str


class VendorUpdate(BaseModel):
    vendor_name: str
    vendor_contact: str


# ── 엔드포인트 ────────────────────────────────────────────────


@router.post("", status_code=201)
def create_work_order(
    body: WorkOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """WO-F01: 결함 신고 접수 + AI 분류 + 자동 배정"""
    svc = WorkOrderService(db=db)
    try:
        wo = svc.create_work_order(
            description=body.description,
            reported_by=current_user.id,
            room_no=body.room_no,
            category=body.category,
            severity=body.severity,
            location=body.location,
            photo_urls=body.photo_urls,
        )
    except Exception as exc:
        logger.error("WO 생성 실패: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return wo


@router.get("")
def list_work_orders(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    assigned_to: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """Work Order 목록 조회 (필터 + 정렬)"""
    svc = WorkOrderService(db=db)
    return svc.list_work_orders(
        status=status,
        severity=severity,
        assigned_to=assigned_to,
        limit=limit,
        offset=offset,
    )


@router.get("/stats")
def get_stats(
    severity: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """WO-F41: 통계 집계"""
    svc = WorkOrderService(db=db)
    return svc.get_stats(severity=severity, category=category)


@router.get("/kpi")
def get_kpi(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """WO-F42: 주간 KPI 리포트"""
    svc = WorkOrderService(db=db)
    return svc.get_weekly_kpi()


@router.get("/{wo_id}")
def get_work_order(
    wo_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """단건 조회"""
    from app.database.models import WorkOrder
    wo = db.query(WorkOrder).filter(WorkOrder.id == wo_id).first()
    if not wo:
        raise HTTPException(status_code=404, detail="Work Order를 찾을 수 없습니다")
    return WorkOrderService(db=db)._wo_to_dict(wo)


@router.patch("/{wo_id}/status")
def update_status(
    wo_id: str,
    body: StatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """WO-F30: 상태 변경"""
    svc = WorkOrderService(db=db)
    try:
        return svc.update_status(wo_id, body.status, current_user.id, body.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/{wo_id}/complete")
def complete_work_order(
    wo_id: str,
    body: CompleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """WO-F31: 완료 처리 (처리 내용·소요시간·부품 필수)"""
    svc = WorkOrderService(db=db)
    try:
        return svc.complete_work_order(
            wo_id=wo_id,
            resolution_note=body.resolution_note,
            actual_duration_min=body.actual_duration_min,
            parts_used=body.parts_used or [],
            changed_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/{wo_id}/category")
def update_category(
    wo_id: str,
    body: CategoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """WO-F13: 카테고리 수동 수정 + 이력 기록"""
    svc = WorkOrderService(db=db)
    try:
        return svc.update_category(wo_id, body.category, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class PhotosAdd(BaseModel):
    photo_urls: list[str]


@router.post("/{wo_id}/photos")
def add_photos(
    wo_id: str,
    body: PhotosAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """사진 URL 추가 — 기존 photo_urls에 append"""
    from app.database.models import WorkOrder
    wo = db.query(WorkOrder).filter(WorkOrder.id == wo_id).first()
    if not wo:
        raise HTTPException(status_code=404, detail="Work Order를 찾을 수 없습니다")

    existing = list(wo.photo_urls or [])
    wo.photo_urls = existing + [u for u in body.photo_urls if u not in existing]
    db.commit()
    db.refresh(wo)
    return WorkOrderService(db=db)._wo_to_dict(wo)


@router.patch("/{wo_id}/vendor")
def assign_vendor(
    wo_id: str,
    body: VendorUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """WO-F23: 외부 업체 배정"""
    from app.work_order.assigner import AutoAssigner
    assigner = AutoAssigner(db=db)
    return assigner.assign_external_vendor(
        wo_id=wo_id,
        vendor_name=body.vendor_name,
        vendor_contact=body.vendor_contact,
        changed_by=current_user.id,
    )
