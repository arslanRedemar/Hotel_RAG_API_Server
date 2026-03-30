"""Revenue Management Celery 태스크 TDD 테스트 (RM-F01, F20, F40)

- generate_forecasts_task: 30일 수요 예측 생성
- generate_recommendations_task: AI 요율 권고 생성
- collect_daily_metrics_task: 일간 성과 지표 수집
"""

from datetime import date, timedelta
from unittest.mock import patch


class TestGenerateForecastsTask:

    def test_generates_forecasts_for_days_ahead(self, db):
        """generate_forecasts_task()는 days_ahead일치 예측 데이터 생성"""
        from app.tasks.revenue_tasks import generate_forecasts_task

        with patch("app.revenue.crud.get_events_for_date", return_value=[]), \
             patch("app.revenue.crud.get_daily_metrics", return_value=None):
            count = generate_forecasts_task(db=db, days_ahead=3)

        assert count >= 1

    def test_skips_existing_forecasts(self, db):
        """이미 예측이 있는 날짜는 건너뜀 (멱등성)"""
        from app.tasks.revenue_tasks import generate_forecasts_task

        with patch("app.revenue.crud.get_events_for_date", return_value=[]), \
             patch("app.revenue.crud.get_daily_metrics", return_value=None):
            generate_forecasts_task(db=db, days_ahead=2)
            count2 = generate_forecasts_task(db=db, days_ahead=2)

        assert count2 == 0  # 두 번째는 이미 있어서 0개 생성

    def test_returns_integer_count(self, db):
        """반환값은 생성된 건수(int)"""
        from app.tasks.revenue_tasks import generate_forecasts_task

        with patch("app.revenue.crud.get_events_for_date", return_value=[]), \
             patch("app.revenue.crud.get_daily_metrics", return_value=None):
            result = generate_forecasts_task(db=db, days_ahead=1)

        assert isinstance(result, int)


class TestGenerateRecommendationsTask:

    def test_generates_recommendations_for_days_ahead(self, db):
        """generate_recommendations_task()는 days_ahead일치 권고 생성"""
        from app.tasks.revenue_tasks import generate_recommendations_task

        mock_rec = {
            "recommendation_date": __import__("datetime").datetime.utcnow(),
            "stay_date": date.today() + timedelta(days=1),
            "recommended_rate": 120000,
            "current_rate": 100000,
            "rate_change_pct": 20.0,
            "reasoning": "테스트 권고",
            "confidence": 0.85,
            "los_restriction": None,
            "action_taken": "pending",
        }

        async def fake_recommend(stay_date):
            return {**mock_rec, "stay_date": stay_date}

        with patch("app.tasks.revenue_tasks.RateRecommendationEngine") as MockEngine:
            instance = MockEngine.return_value
            instance.recommend = fake_recommend
            count = generate_recommendations_task(db=db, days_ahead=2)

        assert count >= 1

    def test_returns_integer_count(self, db):
        """반환값은 생성된 건수(int)"""
        from app.tasks.revenue_tasks import generate_recommendations_task

        async def fake_recommend(stay_date):
            return {
                "recommendation_date": __import__("datetime").datetime.utcnow(),
                "stay_date": stay_date,
                "recommended_rate": 110000,
                "current_rate": 100000,
                "rate_change_pct": 10.0,
                "reasoning": "테스트",
                "confidence": 0.80,
                "los_restriction": None,
                "action_taken": "pending",
            }

        with patch("app.tasks.revenue_tasks.RateRecommendationEngine") as MockEngine:
            instance = MockEngine.return_value
            instance.recommend = fake_recommend
            result = generate_recommendations_task(db=db, days_ahead=1)

        assert isinstance(result, int)


class TestCollectDailyMetricsTask:

    def test_collect_saves_to_db(self, db):
        """collect_daily_metrics_task()는 DailyMetrics 레코드 저장"""
        from app.tasks.revenue_tasks import collect_daily_metrics_task
        from app.database.models import DailyMetrics

        metrics_data = {
            "report_date": date.today() - timedelta(days=1),
            "total_rooms": 100,
            "occupied_rooms": 80,
            "occupancy_rate": 80.0,
            "adr": 120000.0,
            "revpar": 96000.0,
            "total_revenue": 9600000.0,
            "channel_breakdown": {"ota": 45, "direct": 40, "gds": 15},
            "ota_commission": 500000.0,
        }

        collect_daily_metrics_task(data=metrics_data, db=db)

        saved = db.query(DailyMetrics).filter_by(
            report_date=metrics_data["report_date"]
        ).first()
        assert saved is not None
        assert float(saved.occupancy_rate) == 80.0

    def test_collect_returns_saved_id(self, db):
        """저장 후 row id 반환"""
        from app.tasks.revenue_tasks import collect_daily_metrics_task

        data = {
            "report_date": date.today() - timedelta(days=2),
            "total_rooms": 100,
            "occupied_rooms": 70,
            "occupancy_rate": 70.0,
            "adr": 110000.0,
            "revpar": 77000.0,
            "total_revenue": 7700000.0,
        }

        result = collect_daily_metrics_task(data=data, db=db)
        assert "id" in result
