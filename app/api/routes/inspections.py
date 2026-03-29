"""Compliance & Audit API 엔드포인트 (CA-F01~F13, CA-F20~F21, CA-F30~F32)"""

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.connection import get_db
from app.database.models import User
from app.inspections.anomaly_detector import AnomalyDetector
from app.inspections.report_generator import InspectionReportGenerator
from app.inspections.service import InspectionService

router = APIRouter(tags=["Compliance & Audit"])
logger = logging.getLogger(__name__)


# ── 요청/응답 스키마 ──────────────────────────────────────────


class TemplateItemSchema(BaseModel):
    id: str
    category: str
    description: str
    required: bool = True
    photo_required_on_ng: bool = False
    legal_ref: Optional[str] = None
    sop_link: Optional[str] = None


class TemplateCreate(BaseModel):
    name: str
    type: str
    frequency: str = "monthly"
    frequency_day: Optional[int] = None
    department_id: Optional[int] = None
    legal_reference: Optional[str] = None
    items: list[TemplateItemSchema]


class RecordItemSchema(BaseModel):
    item_id: str
    result: str  # OK | NG | NA
    note: Optional[str] = None
    photo_url: Optional[str] = None


class RecordSubmit(BaseModel):
    template_id: str
    location: str
    inspected_at: datetime
    schedule_id: Optional[int] = None
    source: str = "mobile"
    items: list[RecordItemSchema]


class CorrectiveActionCreate(BaseModel):
    item_id: str
    action: str
    work_order_id: Optional[str] = None
    verification_photo_url: Optional[str] = None
    auto_create_wo: bool = False  # CA-F06: True면 WO 자동 생성


class ScheduleGenerateRequest(BaseModel):
    months: int = 12


class ReportRequest(BaseModel):
    from_date: str
    to_date: str
    types: Optional[list[str]] = None
    department_id: Optional[int] = None
    inspector_id: Optional[int] = None


# ── 템플릿 CRUD (CA-F04) ──────────────────────────────────────


@router.post("/inspection-templates", status_code=201)
def create_template(
    body: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """점검 체크리스트 템플릿 생성"""
    svc = InspectionService(db=db)
    return svc.create_template(body.model_dump(), created_by=current_user.id)


@router.get("/inspection-templates")
def list_templates(
    type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """템플릿 목록 조회"""
    svc = InspectionService(db=db)
    return svc.list_templates(type=type, is_active=is_active)


@router.get("/inspection-templates/{template_id}")
def get_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """템플릿 단건 조회"""
    svc = InspectionService(db=db)
    tpl = svc.get_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다")
    return tpl


@router.post("/inspection-templates/{template_id}/schedules")
def generate_schedules(
    template_id: str,
    body: ScheduleGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """템플릿의 점검 일정 자동 생성 (CA-F10)"""
    svc = InspectionService(db=db)
    return svc.generate_schedules(template_id, months=body.months)


# ── 스케줄 조회 (CA-F10, F13) ─────────────────────────────────


@router.get("/inspection-schedules")
def list_schedules(
    template_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """점검 일정 목록 조회 (캘린더 뷰용)"""
    svc = InspectionService(db=db)
    return svc.get_schedules(
        template_id=template_id,
        status=status,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/inspection-schedules/today")
def get_today_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """오늘 점검 목록"""
    svc = InspectionService(db=db)
    return svc.get_today_schedules()


# ── 점검 기록 (CA-F01~F06) ────────────────────────────────────


@router.post("/inspection-records", status_code=201)
def submit_record(
    body: RecordSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """점검 기록 제출 (불변, 전자서명 자동 생성)"""
    svc = InspectionService(db=db)
    try:
        record = svc.submit_record(
            template_id=body.template_id,
            location=body.location,
            inspector_id=current_user.id,
            inspector_name=current_user.name,
            items=[item.model_dump() for item in body.items],
            inspected_at=body.inspected_at,
            schedule_id=body.schedule_id,
            source=body.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return record


@router.get("/inspection-records")
def list_records(
    type: Optional[str] = Query(None),
    inspector_id: Optional[int] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """점검 기록 목록 조회"""
    svc = InspectionService(db=db)
    return svc.list_records(
        type=type,
        inspector_id=inspector_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


@router.get("/inspection-records/{record_id}")
def get_record(
    record_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """점검 기록 단건 조회"""
    svc = InspectionService(db=db)
    record = svc.get_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="점검 기록을 찾을 수 없습니다")
    return record


# ── 조치 이력 (CA-F06) ────────────────────────────────────────


@router.post("/inspection-records/{record_id}/corrective-actions", status_code=201)
def add_corrective_action(
    record_id: str,
    body: CorrectiveActionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """NG 항목 조치 이력 추가"""
    svc = InspectionService(db=db)
    return svc.add_corrective_action(
        record_id=record_id,
        item_id=body.item_id,
        action=body.action,
        completed_by=current_user.id,
        work_order_id=body.work_order_id,
        verification_photo_url=body.verification_photo_url,
        auto_create_wo=body.auto_create_wo,
    )


@router.get("/inspection-records/{record_id}/corrective-actions")
def get_corrective_actions(
    record_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """조치 이력 목록 조회"""
    svc = InspectionService(db=db)
    return svc.get_corrective_actions(record_id)


# ── 이상 감지 (CA-F20~F21) ────────────────────────────────────


@router.get("/inspections/anomalies")
def get_anomalies(
    days: int = Query(28, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """이상 패턴 목록 조회 (반복 NG, 구역 집중)"""
    svc = InspectionService(db=db)
    records = svc.list_records(limit=1000)
    detector = AnomalyDetector()
    return detector.analyze_all(records)


# ── 보고서 (CA-F30~F32) ───────────────────────────────────────


@router.get("/inspection-reports/stats")
def get_report_stats(
    type: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """점검 통계 집계"""
    svc = InspectionService(db=db)
    return svc.get_stats(type=type, from_date=from_date, to_date=to_date)


@router.post("/inspection-reports/generate")
def generate_report(
    body: ReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """감사 보고서 PDF 생성 (CA-F30)"""
    svc = InspectionService(db=db)
    records = svc.list_records(
        type=body.types[0] if body.types and len(body.types) == 1 else None,
        inspector_id=body.inspector_id,
        from_date=body.from_date,
        to_date=body.to_date,
        limit=10000,
    )

    if not records:
        raise HTTPException(status_code=404, detail="조건에 해당하는 점검 기록이 없습니다")

    generator = InspectionReportGenerator()
    pdf_bytes = generator.generate(
        records=records,
        filter_info=body.model_dump(),
    )

    filename = f"inspection_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
