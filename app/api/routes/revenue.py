"""Revenue Management API 엔드포인트 (RM-F01, F20~22, F30~31, F40~41)"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.connection import get_db
from app.database.models import User
from app.revenue.crud import (
    get_daily_metrics_range,
    get_demand_forecasts_range,
    get_recommendations,
)
from app.revenue.group_simulator import GroupBookingSimulator

router = APIRouter(prefix="/revenue", tags=["Revenue Management"])
logger = logging.getLogger(__name__)


# ── 요청 / 응답 스키마 ────────────────────────────────────────


class DailyMetricsCreate(BaseModel):
    report_date: date
    total_rooms: int
    occupied_rooms: int
    occupancy_rate: float
    adr: float
    revpar: float
    total_revenue: float
    channel_breakdown: Optional[dict] = None
    ota_commission: Optional[float] = None


class DecideRecommendationRequest(BaseModel):
    action: Literal["accepted", "modified", "rejected"]
    actual_rate: Optional[float] = None
    rejection_reason: Optional[str] = None


class GroupSimulationRequest(BaseModel):
    rooms_requested: int
    check_in: date
    check_out: date
    proposed_rate: float

    @field_validator("check_out")
    @classmethod
    def checkout_after_checkin(cls, v: date, info) -> date:
        if "check_in" in info.data and v <= info.data["check_in"]:
            raise ValueError("check_out은 check_in 이후여야 합니다")
        return v


class LocalEventCreate(BaseModel):
    name: str
    type: Optional[str] = None
    start_date: date
    end_date: date
    venue: Optional[str] = None
    expected_attendance: Optional[int] = None
    impact_level: Literal["low", "medium", "high", "very_high"] = "medium"
    source: Optional[str] = None


# ── 엔드포인트 ────────────────────────────────────────────────


@router.get("/dashboard")
def get_dashboard(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """RevPAR / ADR / 점유율 / 채널 믹스 대시보드 (RM-F40)"""
    if not to_date:
        to_date = date.today()
    if not from_date:
        from_date = to_date - timedelta(days=30)

    metrics = get_daily_metrics_range(from_date, to_date)

    if metrics:
        revpar_avg = sum(m["revpar"] for m in metrics) / len(metrics)
        adr_avg = sum(m["adr"] for m in metrics) / len(metrics)
        occupancy_avg = sum(m["occupancy_rate"] for m in metrics) / len(metrics)
        total_revenue = sum(m["total_revenue"] for m in metrics)
        total_ota = sum(m["ota_commission"] or 0 for m in metrics)
    else:
        revpar_avg = adr_avg = occupancy_avg = total_revenue = total_ota = 0.0

    channel_totals: dict = defaultdict(float)
    for m in metrics:
        if m.get("channel_breakdown"):
            for channel, pct in m["channel_breakdown"].items():
                channel_totals[channel] += pct
    channel_avg = (
        {k: round(v / len(metrics), 1) for k, v in channel_totals.items()}
        if metrics
        else {}
    )

    pending_recs = get_recommendations(
        from_date=date.today(),
        to_date=date.today() + timedelta(days=14),
        status="pending",
    )

    return {
        "summary": {
            "revpar_avg": round(revpar_avg, 2),
            "adr_avg": round(adr_avg, 2),
            "occupancy_avg": round(occupancy_avg, 2),
            "total_revenue": round(total_revenue, 2),
            "total_ota_commission": round(total_ota, 2),
        },
        "channel_mix": channel_avg,
        "time_series": metrics,
        "pending_recommendations": pending_recs,
    }


@router.post("/metrics", status_code=201)
def save_metrics(
    body: DailyMetricsCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """일간 성과 지표 수동 입력 (RM-F01)"""
    from app.database.models import DailyMetrics

    existing = db.query(DailyMetrics).filter(
        DailyMetrics.report_date == body.report_date
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="해당 날짜 지표가 이미 존재합니다")

    row = DailyMetrics(
        report_date=body.report_date,
        total_rooms=body.total_rooms,
        occupied_rooms=body.occupied_rooms,
        occupancy_rate=body.occupancy_rate,
        adr=body.adr,
        revpar=body.revpar,
        total_revenue=body.total_revenue,
        channel_breakdown=body.channel_breakdown,
        ota_commission=body.ota_commission,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="해당 날짜 지표가 이미 존재합니다")
    db.refresh(row)
    return {"id": row.id}


@router.get("/recommendations")
def list_recommendations(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    status: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
) -> Any:
    """AI 요율 권고 목록 조회 (RM-F20)"""
    if not to_date:
        to_date = date.today() + timedelta(days=30)
    if not from_date:
        from_date = date.today()

    return get_recommendations(from_date=from_date, to_date=to_date, status=status)


@router.post("/recommendations/{rec_id}/decide")
def decide_recommendation(
    rec_id: int,
    body: DecideRecommendationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """AI 요율 권고 수락/수정/거절 (RM-F21)"""
    from app.database.models import RateRecommendation

    rec = db.query(RateRecommendation).filter(RateRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="권고를 찾을 수 없습니다")

    rec.action_taken = body.action
    if body.actual_rate is not None:
        rec.actual_rate_applied = body.actual_rate
    if body.rejection_reason:
        rec.rejection_reason = body.rejection_reason
    rec.decided_by = current_user.id
    rec.decided_at = datetime.now()

    db.commit()
    return {"status": "ok"}


@router.post("/simulate/group")
def simulate_group_booking(
    body: GroupSimulationRequest,
    current_user: User = Depends(get_current_user),
) -> Any:
    """단체 예약 수락/거절 시뮬레이션 (RM-F30)"""
    simulator = GroupBookingSimulator()
    return simulator.simulate(
        rooms_requested=body.rooms_requested,
        check_in=body.check_in,
        check_out=body.check_out,
        proposed_rate=body.proposed_rate,
    )


@router.get("/forecast")
def get_forecast(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    current_user: User = Depends(get_current_user),
) -> Any:
    """수요 예측 목록 조회 (RM-F10)"""
    if not to_date:
        to_date = date.today() + timedelta(days=30)
    if not from_date:
        from_date = date.today()

    return get_demand_forecasts_range(from_date, to_date)


@router.post("/events", status_code=201)
def create_event(
    body: LocalEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """로컬 이벤트 등록 (RM-F02)"""
    from app.database.models import LocalEvent

    event = LocalEvent(
        name=body.name,
        type=body.type,
        start_date=body.start_date,
        end_date=body.end_date,
        venue=body.venue,
        expected_attendance=body.expected_attendance,
        impact_level=body.impact_level,
        source=body.source,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {"id": event.id}


@router.get("/events")
def list_events(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """로컬 이벤트 목록 조회"""
    from app.database.models import LocalEvent
    from sqlalchemy import cast, Date

    q = db.query(LocalEvent)
    if from_date:
        q = q.filter(cast(LocalEvent.end_date, Date) >= from_date)
    if to_date:
        q = q.filter(cast(LocalEvent.start_date, Date) <= to_date)

    events = q.order_by(LocalEvent.start_date).all()
    return [
        {
            "id": e.id,
            "name": e.name,
            "type": e.type,
            "start_date": e.start_date,
            "end_date": e.end_date,
            "impact_level": e.impact_level,
            "venue": e.venue,
        }
        for e in events
    ]
