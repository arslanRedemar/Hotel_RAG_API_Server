"""Revenue Management CRUD 함수 — DB 세션 없이 모킹 가능하도록 모듈 레벨 함수로 작성"""

from datetime import date


def get_daily_metrics(report_date: date) -> dict | None:
    """특정 날짜의 성과 지표 조회"""
    from app.database.connection import SessionLocal
    from app.database.models import DailyMetrics
    from sqlalchemy import cast, Date

    db = SessionLocal()
    try:
        row = db.query(DailyMetrics).filter(
            cast(DailyMetrics.report_date, Date) == report_date
        ).first()
        if not row:
            return None
        return {
            "report_date": row.report_date,
            "total_rooms": row.total_rooms,
            "occupied_rooms": row.occupied_rooms,
            "occupancy_rate": float(row.occupancy_rate),
            "adr": float(row.adr),
            "revpar": float(row.revpar),
            "total_revenue": float(row.total_revenue),
            "channel_breakdown": row.channel_breakdown,
            "ota_commission": float(row.ota_commission) if row.ota_commission else None,
        }
    finally:
        db.close()


def get_daily_metrics_range(from_date: date, to_date: date) -> list[dict]:
    from app.database.connection import SessionLocal
    from app.database.models import DailyMetrics
    from sqlalchemy import cast, Date

    db = SessionLocal()
    try:
        rows = db.query(DailyMetrics).filter(
            cast(DailyMetrics.report_date, Date) >= from_date,
            cast(DailyMetrics.report_date, Date) <= to_date,
        ).order_by(DailyMetrics.report_date).all()
        return [
            {
                "report_date": r.report_date,
                "occupancy_rate": float(r.occupancy_rate),
                "adr": float(r.adr),
                "revpar": float(r.revpar),
                "total_revenue": float(r.total_revenue),
                "ota_commission": float(r.ota_commission) if r.ota_commission else None,
                "channel_breakdown": r.channel_breakdown,
            }
            for r in rows
        ]
    finally:
        db.close()


def save_daily_metrics(data: dict) -> dict:
    from app.database.connection import SessionLocal
    from app.database.models import DailyMetrics

    db = SessionLocal()
    try:
        row = DailyMetrics(**data)
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"id": row.id}
    finally:
        db.close()


def get_events_for_date(stay_date: date) -> list[dict]:
    from app.database.connection import SessionLocal
    from app.database.models import LocalEvent
    from sqlalchemy import cast, Date

    db = SessionLocal()
    try:
        rows = db.query(LocalEvent).filter(
            cast(LocalEvent.start_date, Date) <= stay_date,
            cast(LocalEvent.end_date, Date) >= stay_date,
        ).all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "type": r.type,
                "impact_level": r.impact_level,
                "venue": r.venue,
            }
            for r in rows
        ]
    finally:
        db.close()


def get_competitor_rates(stay_date: date) -> list[dict]:
    from app.database.connection import SessionLocal
    from app.database.models import CompetitorRate
    from sqlalchemy import cast, Date
    import datetime as dt

    db = SessionLocal()
    try:
        today = dt.date.today()
        rows = db.query(CompetitorRate).filter(
            cast(CompetitorRate.stay_date, Date) == stay_date,
            cast(CompetitorRate.snapshot_date, Date) == today,
        ).all()
        return [
            {
                "competitor_name": r.competitor_name,
                "rate_min": float(r.rate_min) if r.rate_min else None,
                "rate_max": float(r.rate_max) if r.rate_max else None,
                "is_soldout": r.is_soldout,
            }
            for r in rows
        ]
    finally:
        db.close()


def save_competitor_rate(data: dict) -> dict:
    from app.database.connection import SessionLocal
    from app.database.models import CompetitorRate

    db = SessionLocal()
    try:
        row = CompetitorRate(**data)
        db.add(row)
        db.commit()
        return {"id": row.id}
    finally:
        db.close()


def get_demand_forecast(stay_date: date) -> dict | None:
    from app.database.connection import SessionLocal
    from app.database.models import DemandForecast
    from sqlalchemy import cast, Date

    db = SessionLocal()
    try:
        row = (
            db.query(DemandForecast)
            .filter(
                cast(DemandForecast.stay_date, Date) == stay_date,
            )
            .order_by(DemandForecast.forecast_date.desc())
            .first()
        )
        if not row:
            return None
        return {
            "id": row.id,
            "stay_date": row.stay_date,
            "predicted_occupancy_base": float(row.predicted_occupancy_base)
            if row.predicted_occupancy_base
            else None,
            "predicted_occupancy_opt": float(row.predicted_occupancy_opt)
            if row.predicted_occupancy_opt
            else None,
            "predicted_occupancy_pess": float(row.predicted_occupancy_pess)
            if row.predicted_occupancy_pess
            else None,
        }
    finally:
        db.close()


def get_demand_forecasts_range(from_date: date, to_date: date) -> list[dict]:
    from app.database.connection import SessionLocal
    from app.database.models import DemandForecast
    from sqlalchemy import cast, Date

    db = SessionLocal()
    try:
        rows = db.query(DemandForecast).filter(
            cast(DemandForecast.stay_date, Date) >= from_date,
            cast(DemandForecast.stay_date, Date) <= to_date,
        ).all()
        return [
            {
                "id": r.id,
                "stay_date": r.stay_date,
                "predicted_occupancy_base": float(r.predicted_occupancy_base)
                if r.predicted_occupancy_base
                else None,
            }
            for r in rows
        ]
    finally:
        db.close()


def update_forecast_actual(forecast_id: int, actual_occupancy: float, mape: float) -> None:
    from app.database.connection import SessionLocal
    from app.database.models import DemandForecast

    db = SessionLocal()
    try:
        row = db.query(DemandForecast).filter(DemandForecast.id == forecast_id).first()
        if row:
            row.actual_occupancy = actual_occupancy
            row.mape = mape
            db.commit()
    finally:
        db.close()


def get_latest_pickup(stay_date: date) -> dict | None:
    from app.database.connection import SessionLocal
    from app.database.models import ReservationPickup
    from sqlalchemy import cast, Date

    db = SessionLocal()
    try:
        row = (
            db.query(ReservationPickup)
            .filter(
                cast(ReservationPickup.stay_date, Date) == stay_date,
            )
            .order_by(ReservationPickup.snapshot_date.desc())
            .first()
        )
        if not row:
            return None
        return {
            "stay_date": row.stay_date,
            "snapshot_date": row.snapshot_date,
            "confirmed_rooms": row.confirmed_rooms,
            "total_rooms": row.total_rooms,
            "pickup_rate": float(row.pickup_rate),
        }
    finally:
        db.close()


def get_pickup_snapshots(stay_date: date) -> list[dict]:
    from app.database.connection import SessionLocal
    from app.database.models import ReservationPickup
    from sqlalchemy import cast, Date

    db = SessionLocal()
    try:
        rows = (
            db.query(ReservationPickup)
            .filter(
                cast(ReservationPickup.stay_date, Date) == stay_date,
            )
            .order_by(ReservationPickup.snapshot_date)
            .all()
        )
        return [
            {
                "stay_date": r.stay_date,
                "snapshot_date": r.snapshot_date,
                "pickup_rate": float(r.pickup_rate),
            }
            for r in rows
        ]
    finally:
        db.close()


def get_recommendations(
    from_date: date, to_date: date, status: str | None = None
) -> list[dict]:
    from app.database.connection import SessionLocal
    from app.database.models import RateRecommendation
    from sqlalchemy import cast, Date

    db = SessionLocal()
    try:
        q = db.query(RateRecommendation).filter(
            cast(RateRecommendation.stay_date, Date) >= from_date,
            cast(RateRecommendation.stay_date, Date) <= to_date,
        )
        if status:
            q = q.filter(RateRecommendation.action_taken == status)
        rows = q.order_by(RateRecommendation.stay_date).all()
        return [
            {
                "id": r.id,
                "stay_date": r.stay_date,
                "recommended_rate": float(r.recommended_rate),
                "current_rate": float(r.current_rate) if r.current_rate else None,
                "rate_change_pct": float(r.rate_change_pct) if r.rate_change_pct else None,
                "reasoning": r.reasoning,
                "confidence": float(r.confidence) if r.confidence else None,
                "action_taken": r.action_taken,
            }
            for r in rows
        ]
    finally:
        db.close()


def get_recommendations_range(from_date: date, to_date: date) -> list[dict]:
    return get_recommendations(from_date, to_date)


def save_recommendation(data: dict) -> dict:
    from app.database.connection import SessionLocal
    from app.database.models import RateRecommendation

    db = SessionLocal()
    try:
        row = RateRecommendation(**data)
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"id": row.id}
    finally:
        db.close()


def update_recommendation(rec_id: int, data: dict) -> None:
    from app.database.connection import SessionLocal
    from app.database.models import RateRecommendation

    db = SessionLocal()
    try:
        row = db.query(RateRecommendation).filter(RateRecommendation.id == rec_id).first()
        if row:
            for k, v in data.items():
                setattr(row, k, v)
            db.commit()
    finally:
        db.close()


def get_current_pms_rate(stay_date: date) -> float:
    """PMS에서 현재 요율 조회 (간단히 0 반환, 실제는 PMS 연동)"""
    return 0.0


def get_remaining_rooms(stay_date: date) -> int:
    """잔여 객실 수 조회"""
    from app.core.config import settings

    pickup = get_latest_pickup(stay_date)
    if not pickup:
        return settings.total_rooms
    confirmed = int(pickup["confirmed_rooms"])
    return max(0, settings.total_rooms - confirmed)


def get_yoy_pickup(stay_date: date) -> float:
    """전년 동기 픽업률"""
    yoy_date = stay_date.replace(year=stay_date.year - 1)
    pickup = get_latest_pickup(yoy_date)
    return pickup["pickup_rate"] if pickup else 0.0
