"""Revenue Management Celery 태스크 (RM-F01, F10, F20, F40)

Celery Beat 스케줄:
- generate_forecasts_task     : 매일 06:00 — 30일 수요 예측 업데이트
- generate_recommendations_task: 매일 08:00 — AI 요율 권고 생성
- collect_daily_metrics_task  : 직접 호출 (PMS 연동 또는 수동 배치)

테스트에서는 함수에 db=를 직접 주입해 순수 로직만 검증.
"""

import logging
from datetime import date, timedelta

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.revenue.recommendation_engine import RateRecommendationEngine

logger = logging.getLogger(__name__)

celery_app = Celery("hotel_ax", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.beat_schedule = {
    "update-demand-forecasts": {
        "task": "app.tasks.revenue_tasks.celery_generate_forecasts",
        "schedule": crontab(hour=6, minute=0),
    },
    "generate-rate-recommendations": {
        "task": "app.tasks.revenue_tasks.celery_generate_recommendations",
        "schedule": crontab(hour=8, minute=0),
    },
}


# ── 수요 예측 생성 ───────────────────────────────────────────────

def generate_forecasts_task(db=None, days_ahead: int = 30) -> int:
    """향후 days_ahead일간 수요 예측 생성 (멱등성 보장).

    Returns: 생성된 예측 건수
    """
    from app.database.connection import SessionLocal
    from app.database.models import DemandForecast
    from app.revenue.demand_forecaster import DemandForecaster

    own_db = False
    if db is None:
        db = SessionLocal()
        own_db = True

    try:
        forecaster = DemandForecaster()
        total_created = 0

        for day_offset in range(1, days_ahead + 1):
            stay_date = date.today() + timedelta(days=day_offset)

            # 이미 예측이 있는 날짜는 건너뜀
            existing = (
                db.query(DemandForecast)
                .filter(DemandForecast.stay_date == stay_date)
                .first()
            )
            if existing:
                continue

            try:
                result = forecaster.forecast(stay_date)
                row = DemandForecast(
                    forecast_date=result["forecast_date"],
                    stay_date=result["stay_date"],
                    predicted_occupancy_base=result["predicted_occupancy_base"],
                    predicted_occupancy_opt=result["predicted_occupancy_opt"],
                    predicted_occupancy_pess=result["predicted_occupancy_pess"],
                )
                db.add(row)
                total_created += 1
            except Exception as exc:
                logger.error("예측 생성 실패 stay_date=%s: %s", stay_date, exc)

        db.commit()
        logger.info("수요 예측 생성 완료: %d건", total_created)
        return total_created
    finally:
        if own_db:
            db.close()


# ── 요율 권고 생성 ───────────────────────────────────────────────

def generate_recommendations_task(db=None, days_ahead: int = 30) -> int:
    """향후 days_ahead일간 AI 요율 권고 생성.

    Returns: 생성된 권고 건수
    """
    from app.database.connection import SessionLocal
    from app.database.models import RateRecommendation

    own_db = False
    if db is None:
        db = SessionLocal()
        own_db = True

    try:
        engine = RateRecommendationEngine()
        total_created = 0

        for day_offset in range(1, days_ahead + 1):
            stay_date = date.today() + timedelta(days=day_offset)

            # 이미 pending 권고가 있으면 건너뜀
            existing = (
                db.query(RateRecommendation)
                .filter(
                    RateRecommendation.stay_date == stay_date,
                    RateRecommendation.action_taken == "pending",
                )
                .first()
            )
            if existing:
                continue

            try:
                import asyncio
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(engine.recommend(stay_date))
                finally:
                    loop.close()
                row = RateRecommendation(
                    recommendation_date=result["recommendation_date"],
                    stay_date=result["stay_date"],
                    recommended_rate=result["recommended_rate"],
                    current_rate=result.get("current_rate"),
                    rate_change_pct=result.get("rate_change_pct"),
                    reasoning=result.get("reasoning", ""),
                    confidence=result.get("confidence"),
                    los_restriction=result.get("los_restriction"),
                    action_taken="pending",
                )
                db.add(row)
                total_created += 1
            except Exception as exc:
                logger.error("권고 생성 실패 stay_date=%s: %s", stay_date, exc)

        db.commit()
        logger.info("요율 권고 생성 완료: %d건", total_created)
        return total_created
    finally:
        if own_db:
            db.close()


# ── 일간 성과 지표 저장 ──────────────────────────────────────────

def collect_daily_metrics_task(data: dict, db=None) -> dict:
    """일간 성과 지표를 DB에 저장.

    Args:
        data: DailyMetrics 필드 딕셔너리
        db: SQLAlchemy 세션 (None이면 새 세션 생성)
    Returns:
        {"id": <저장된 row ID>}
    """
    from app.database.connection import SessionLocal
    from app.database.models import DailyMetrics

    own_db = False
    if db is None:
        db = SessionLocal()
        own_db = True

    try:
        row = DailyMetrics(**data)
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info("일간 성과 지표 저장 완료: date=%s", data.get("report_date"))
        return {"id": row.id}
    finally:
        if own_db:
            db.close()


# ── Celery 래퍼 태스크 ─────────────────────────────────────────

@celery_app.task(name="app.tasks.revenue_tasks.celery_generate_forecasts")
def celery_generate_forecasts():
    generate_forecasts_task()


@celery_app.task(name="app.tasks.revenue_tasks.celery_generate_recommendations")
def celery_generate_recommendations():
    generate_recommendations_task()
