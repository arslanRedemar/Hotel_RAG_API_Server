"""Revenue Management 모듈 단위 테스트 (TDD)"""

from datetime import date
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ── GroupBookingSimulator ─────────────────────────────────────

class TestGroupBookingSimulator:

    def _make_simulator(self):
        from app.revenue.group_simulator import GroupBookingSimulator
        return GroupBookingSimulator()

    def _mock_forecast(self, base_occ: float):
        return {"predicted_occupancy_base": base_occ}

    def test_accept_when_group_revenue_clearly_higher(self):
        sim = self._make_simulator()
        check_in = date(2026, 7, 1)
        check_out = date(2026, 7, 3)  # 2박

        # 단체 요율 200,000원, 30실, 2박 = 12,000,000원
        # 개별 예약 기대: 점유율 30% * 30실 * 100,000원 = 900,000원/박 → 훨씬 낮음
        with patch("app.revenue.group_simulator.get_demand_forecast", return_value=self._mock_forecast(30.0)):
            with patch("app.revenue.group_simulator.get_current_pms_rate", return_value=100_000):
                result = sim.simulate(30, check_in, check_out, 200_000)

        assert result["recommendation"] == "accept"

    def test_reject_when_individual_revenue_clearly_higher(self):
        sim = self._make_simulator()
        check_in = date(2026, 8, 1)
        check_out = date(2026, 8, 2)  # 1박

        # 단체 50,000원 * 10실 = 500,000원
        # 개별: 100% * 10실 * 200,000원 = 2,000,000원
        with patch("app.revenue.group_simulator.get_demand_forecast", return_value=self._mock_forecast(100.0)):
            with patch("app.revenue.group_simulator.get_current_pms_rate", return_value=200_000):
                result = sim.simulate(10, check_in, check_out, 50_000)

        assert result["recommendation"] == "reject"

    def test_negotiate_when_revenues_similar(self):
        sim = self._make_simulator()
        check_in = date(2026, 6, 1)
        check_out = date(2026, 6, 2)

        # 단체 100,000원 * 10실 = 1,000,000원
        # 개별: 95% * 10실 * 105,000원 ≈ 997,500원 → 차이 미미
        with patch("app.revenue.group_simulator.get_demand_forecast", return_value=self._mock_forecast(95.0)):
            with patch("app.revenue.group_simulator.get_current_pms_rate", return_value=105_000):
                result = sim.simulate(10, check_in, check_out, 100_000)

        assert result["recommendation"] == "negotiate"

    def test_calculates_nights_correctly(self):
        sim = self._make_simulator()
        check_in = date(2026, 6, 1)
        check_out = date(2026, 6, 4)  # 3박

        with patch("app.revenue.group_simulator.get_demand_forecast", return_value=self._mock_forecast(70.0)):
            with patch("app.revenue.group_simulator.get_current_pms_rate", return_value=120_000):
                result = sim.simulate(5, check_in, check_out, 120_000)

        assert result["nights"] == 3
        assert result["total_room_nights"] == 15  # 5실 * 3박

    def test_daily_breakdown_has_required_fields(self):
        sim = self._make_simulator()
        check_in = date(2026, 6, 1)
        check_out = date(2026, 6, 2)

        with patch("app.revenue.group_simulator.get_demand_forecast", return_value=self._mock_forecast(70.0)):
            with patch("app.revenue.group_simulator.get_current_pms_rate", return_value=120_000):
                result = sim.simulate(10, check_in, check_out, 120_000)

        assert len(result["daily_breakdown"]) == 1
        day = result["daily_breakdown"][0]
        assert {"date", "expected_fill", "rate", "revenue"} <= day.keys()

    def test_opportunity_cost_is_accept_minus_reject(self):
        sim = self._make_simulator()
        check_in = date(2026, 6, 1)
        check_out = date(2026, 6, 2)

        with patch("app.revenue.group_simulator.get_demand_forecast", return_value=self._mock_forecast(70.0)):
            with patch("app.revenue.group_simulator.get_current_pms_rate", return_value=120_000):
                result = sim.simulate(10, check_in, check_out, 150_000)

        expected_opp_cost = result["accept_revenue"] - result["reject_revenue"]
        assert abs(result["opportunity_cost"] - expected_opp_cost) < 0.01

    def test_accept_revenue_equals_rate_times_room_nights(self):
        sim = self._make_simulator()
        check_in = date(2026, 6, 1)
        check_out = date(2026, 6, 3)

        with patch("app.revenue.group_simulator.get_demand_forecast", return_value=self._mock_forecast(70.0)):
            with patch("app.revenue.group_simulator.get_current_pms_rate", return_value=120_000):
                result = sim.simulate(5, check_in, check_out, 100_000)

        # 5실 * 2박 * 100,000 = 1,000,000
        assert result["accept_revenue"] == pytest.approx(1_000_000)


# ── DemandForecaster ──────────────────────────────────────────

class TestDemandForecaster:

    def _make_forecaster(self):
        from app.revenue.demand_forecaster import DemandForecaster
        return DemandForecaster()

    def test_fallback_to_70_when_no_history(self):
        fc = self._make_forecaster()
        target = date(2026, 6, 15)

        with patch("app.revenue.demand_forecaster.get_daily_metrics", return_value=None):
            with patch("app.revenue.demand_forecaster.get_events_for_date", return_value=[]):
                result = fc.forecast(target)

        # 이벤트 없음, 6월 계절 지수 1.0 → base ≈ 70.0
        assert result["predicted_occupancy_base"] == pytest.approx(70.0, abs=5)

    def test_three_scenarios_returned(self):
        fc = self._make_forecaster()
        with patch("app.revenue.demand_forecaster.get_daily_metrics", return_value=None):
            with patch("app.revenue.demand_forecaster.get_events_for_date", return_value=[]):
                result = fc.forecast(date(2026, 6, 15))

        assert "predicted_occupancy_base" in result
        assert "predicted_occupancy_opt" in result
        assert "predicted_occupancy_pess" in result

    def test_optimistic_higher_than_base(self):
        fc = self._make_forecaster()
        with patch("app.revenue.demand_forecaster.get_daily_metrics", return_value=None):
            with patch("app.revenue.demand_forecaster.get_events_for_date", return_value=[]):
                result = fc.forecast(date(2026, 6, 15))

        assert result["predicted_occupancy_opt"] > result["predicted_occupancy_base"]

    def test_pessimistic_lower_than_base(self):
        fc = self._make_forecaster()
        with patch("app.revenue.demand_forecaster.get_daily_metrics", return_value=None):
            with patch("app.revenue.demand_forecaster.get_events_for_date", return_value=[]):
                result = fc.forecast(date(2026, 6, 15))

        assert result["predicted_occupancy_pess"] < result["predicted_occupancy_base"]

    def test_occupancy_within_0_100(self):
        fc = self._make_forecaster()
        # 이벤트 very_high + 성수기(8월) → 100% 초과 방지 확인
        event = {"name": "올림픽", "impact_level": "very_high"}
        with patch("app.revenue.demand_forecaster.get_daily_metrics", return_value={"occupancy_rate": 95.0}):
            with patch("app.revenue.demand_forecaster.get_events_for_date", return_value=[event]):
                result = fc.forecast(date(2026, 8, 1))

        assert result["predicted_occupancy_base"] <= 100.0
        assert result["predicted_occupancy_opt"] <= 100.0
        assert result["predicted_occupancy_pess"] >= 0.0

    def test_event_multiplier_increases_occupancy(self):
        fc = self._make_forecaster()
        no_event_result = None
        event_result = None
        target = date(2026, 6, 15)

        with patch("app.revenue.demand_forecaster.get_daily_metrics", return_value=None):
            with patch("app.revenue.demand_forecaster.get_events_for_date", return_value=[]):
                no_event_result = fc.forecast(target)

            with patch("app.revenue.demand_forecaster.get_events_for_date",
                       return_value=[{"name": "페스티벌", "impact_level": "high"}]):
                event_result = fc.forecast(target)

        assert event_result["predicted_occupancy_base"] > no_event_result["predicted_occupancy_base"]

    def test_historical_data_used_when_available(self):
        fc = self._make_forecaster()
        target = date(2026, 6, 15)

        with patch("app.revenue.demand_forecaster.get_daily_metrics", return_value={"occupancy_rate": 90.0}):
            with patch("app.revenue.demand_forecaster.get_events_for_date", return_value=[]):
                result = fc.forecast(target)

        # 90% 이력 기반 → fallback 70%보다 높아야 함
        assert result["predicted_occupancy_base"] > 70.0

    def test_result_contains_factors(self):
        fc = self._make_forecaster()
        with patch("app.revenue.demand_forecaster.get_daily_metrics", return_value=None):
            with patch("app.revenue.demand_forecaster.get_events_for_date", return_value=[]):
                result = fc.forecast(date(2026, 6, 15))

        assert "factors" in result
        assert "seasonal_factor" in result["factors"]


# ── RateRecommendationEngine ──────────────────────────────────

class TestRateRecommendationEngine:

    def _make_engine(self):
        from app.revenue.recommendation_engine import RateRecommendationEngine
        return RateRecommendationEngine()

    def _mock_context(self):
        return {
            "current_pickup_pct": 60.0, "yoy_pickup_pct": 55.0,
            "remaining_rooms": 40, "total_rooms": 100,
            "yoy_adr": 120_000, "yoy_occ": 70.0,
            "current_rate": 130_000,
            "comp_a_rate": 140_000, "comp_a_soldout": "",
            "comp_b_rate": 135_000, "comp_b_soldout": "(매진)",
            "comp_c_rate": "정보없음", "comp_c_soldout": "",
            "events": "없음", "weather": "맑음", "holiday": "해당없음",
            "forecast_base": 75.0, "forecast_opt": 82.0, "forecast_pess": 68.0,
        }

    def test_returns_recommendation_dict(self):
        engine = self._make_engine()
        mock_llm_response = MagicMock()
        mock_llm_response.content = '{"recommended_rate": 145000, "reasoning": "수요 증가", "confidence": 0.85}'

        with patch.object(engine, "_gather_context", return_value=self._mock_context()):
            with patch.object(engine.llm, "invoke", return_value=mock_llm_response):
                import asyncio
                result = asyncio.get_event_loop().run_until_complete(
                    engine.recommend(date(2026, 6, 15))
                )

        assert "recommended_rate" in result
        assert "reasoning" in result
        assert "confidence" in result

    def test_calculates_rate_change_pct(self):
        engine = self._make_engine()
        mock_llm_response = MagicMock()
        mock_llm_response.content = '{"recommended_rate": 143000, "reasoning": "테스트", "confidence": 0.8}'

        with patch.object(engine, "_gather_context", return_value=self._mock_context()):
            with patch.object(engine.llm, "invoke", return_value=mock_llm_response):
                import asyncio
                result = asyncio.get_event_loop().run_until_complete(
                    engine.recommend(date(2026, 6, 15))
                )

        # 130,000 → 143,000 = +10%
        assert result["rate_change_pct"] == pytest.approx(10.0, abs=0.2)

    def test_json_parse_error_returns_fallback(self):
        engine = self._make_engine()
        mock_llm_response = MagicMock()
        mock_llm_response.content = "JSON이 아닌 응답"

        with patch.object(engine, "_gather_context", return_value=self._mock_context()):
            with patch.object(engine.llm, "invoke", return_value=mock_llm_response):
                import asyncio
                result = asyncio.get_event_loop().run_until_complete(
                    engine.recommend(date(2026, 6, 15))
                )

        # 폴백: 현재 요율 유지, confidence 0
        assert result["recommended_rate"] == 130_000
        assert result["confidence"] == 0.0

    def test_confidence_between_0_and_1(self):
        engine = self._make_engine()
        mock_llm_response = MagicMock()
        mock_llm_response.content = '{"recommended_rate": 140000, "reasoning": "ok", "confidence": 0.92}'

        with patch.object(engine, "_gather_context", return_value=self._mock_context()):
            with patch.object(engine.llm, "invoke", return_value=mock_llm_response):
                import asyncio
                result = asyncio.get_event_loop().run_until_complete(
                    engine.recommend(date(2026, 6, 15))
                )

        assert 0.0 <= result["confidence"] <= 1.0


# ── ForecastAccuracyTracker ───────────────────────────────────

class TestForecastAccuracyTracker:

    def _make_tracker(self):
        from app.revenue.accuracy_tracker import ForecastAccuracyTracker
        return ForecastAccuracyTracker()

    def _make_forecasts(self):
        return [
            {"id": 1, "stay_date": date(2026, 3, 1), "predicted_occupancy_base": 70.0},
            {"id": 2, "stay_date": date(2026, 3, 2), "predicted_occupancy_base": 80.0},
        ]

    def _make_actuals(self):
        return [
            {"report_date": date(2026, 3, 1), "occupancy_rate": 77.0},  # 오차 10%
            {"report_date": date(2026, 3, 2), "occupancy_rate": 72.0},  # 오차 10%
        ]

    def test_mape_calculated_correctly(self):
        tracker = self._make_tracker()
        # 오차: |70-77|/77 = 9.09%, |80-72|/72 = 11.11%  → 평균 ≈ 10.1%

        with patch("app.revenue.accuracy_tracker.get_demand_forecasts_range", return_value=self._make_forecasts()):
            with patch("app.revenue.accuracy_tracker.get_daily_metrics_range", return_value=self._make_actuals()):
                with patch("app.revenue.accuracy_tracker.update_forecast_actual"):
                    result = tracker.calculate_monthly_mape(2026, 3)

        assert result["mape_pct"] == pytest.approx(10.1, abs=0.5)

    def test_empty_forecasts_returns_none_mape(self):
        tracker = self._make_tracker()

        with patch("app.revenue.accuracy_tracker.get_demand_forecasts_range", return_value=[]):
            with patch("app.revenue.accuracy_tracker.get_daily_metrics_range", return_value=[]):
                with patch("app.revenue.accuracy_tracker.update_forecast_actual"):
                    result = tracker.calculate_monthly_mape(2026, 3)

        assert result["mape_pct"] is None

    def test_target_met_when_mape_below_10(self):
        tracker = self._make_tracker()
        forecasts = [{"id": 1, "stay_date": date(2026, 3, 1), "predicted_occupancy_base": 70.0}]
        actuals = [{"report_date": date(2026, 3, 1), "occupancy_rate": 73.0}]  # 오차 4.1%

        with patch("app.revenue.accuracy_tracker.get_demand_forecasts_range", return_value=forecasts):
            with patch("app.revenue.accuracy_tracker.get_daily_metrics_range", return_value=actuals):
                with patch("app.revenue.accuracy_tracker.update_forecast_actual"):
                    result = tracker.calculate_monthly_mape(2026, 3)

        assert result["is_target_met"] is True

    def test_target_not_met_when_mape_above_10(self):
        tracker = self._make_tracker()
        forecasts = [{"id": 1, "stay_date": date(2026, 3, 1), "predicted_occupancy_base": 50.0}]
        actuals = [{"report_date": date(2026, 3, 1), "occupancy_rate": 80.0}]  # 오차 37.5%

        with patch("app.revenue.accuracy_tracker.get_demand_forecasts_range", return_value=forecasts):
            with patch("app.revenue.accuracy_tracker.get_daily_metrics_range", return_value=actuals):
                with patch("app.revenue.accuracy_tracker.update_forecast_actual"):
                    result = tracker.calculate_monthly_mape(2026, 3)

        assert result["is_target_met"] is False

    def test_sample_count_matches(self):
        tracker = self._make_tracker()

        with patch("app.revenue.accuracy_tracker.get_demand_forecasts_range", return_value=self._make_forecasts()):
            with patch("app.revenue.accuracy_tracker.get_daily_metrics_range", return_value=self._make_actuals()):
                with patch("app.revenue.accuracy_tracker.update_forecast_actual"):
                    result = tracker.calculate_monthly_mape(2026, 3)

        assert result["sample_count"] == 2


# ── PMSCollector ──────────────────────────────────────────────

class TestPMSCollector:

    def _make_collector(self):
        from app.revenue.collectors.pms_collector import PMSCollector
        return PMSCollector(base_url="https://pms.test", api_key="test-key")

    def test_collects_daily_metrics(self):
        collector = self._make_collector()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "property": {"total_rooms": 100},
            "statistics": {
                "occupied": 75,
                "occupancy_pct": 75.0,
                "adr": 120000.0,
                "revpar": 90000.0,
                "total_revenue": 9_000_000.0,
            },
            "channel_mix": {"ota": 45, "direct": 35, "gds": 20},
            "ota_commission_total": 200000.0,
        }
        mock_response.raise_for_status = MagicMock()

        import asyncio
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = asyncio.get_event_loop().run_until_complete(
                collector.collect_daily_metrics(date(2026, 3, 1))
            )

        assert result["total_rooms"] == 100
        assert result["occupied_rooms"] == 75
        assert result["adr"] == 120000.0

    def test_pickup_rate_calculated_correctly(self):
        collector = self._make_collector()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "confirmed_reservations": 30,
            "total_rooms": 100,
        }

        import asyncio
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = asyncio.get_event_loop().run_until_complete(
                collector.collect_pickup_data(date(2026, 6, 15))
            )

        assert result["pickup_rate"] == pytest.approx(30.0)
        assert result["confirmed_rooms"] == 30

    def test_returns_correct_report_date(self):
        collector = self._make_collector()
        target = date(2026, 3, 15)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "property": {"total_rooms": 100},
            "statistics": {
                "occupied": 60, "occupancy_pct": 60.0,
                "adr": 110000.0, "revpar": 66000.0, "total_revenue": 6_600_000.0,
            },
        }
        mock_response.raise_for_status = MagicMock()

        import asyncio
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = asyncio.get_event_loop().run_until_complete(
                collector.collect_daily_metrics(target)
            )

        assert result["report_date"] == target


# ── ManualCompetitorRateCollector ────────────────────────────

class TestManualCompetitorRateCollector:

    def test_creates_rate_entry(self):
        from app.revenue.collectors.competitor_collector import ManualCompetitorRateCollector
        collector = ManualCompetitorRateCollector()
        entry = collector.create_rate_entry(
            stay_date=date(2026, 6, 15),
            competitor_name="호텔A",
            rate_min=120_000,
            rate_max=150_000,
            is_soldout=False,
        )
        assert entry["competitor_name"] == "호텔A"
        assert entry["stay_date"] == date(2026, 6, 15)
        assert entry["is_soldout"] is False

    def test_soldout_entry(self):
        from app.revenue.collectors.competitor_collector import ManualCompetitorRateCollector
        collector = ManualCompetitorRateCollector()
        entry = collector.create_rate_entry(
            stay_date=date(2026, 6, 15),
            competitor_name="호텔B",
            rate_min=None,
            rate_max=None,
            is_soldout=True,
        )
        assert entry["is_soldout"] is True


# ── LocalEventCollector ──────────────────────────────────────

class TestLocalEventCollector:

    def test_classify_event_type_concert(self):
        from app.revenue.collectors.event_collector import LocalEventCollector
        collector = LocalEventCollector()
        assert collector._classify_event_type("음악") == "콘서트"

    def test_classify_event_type_sports(self):
        from app.revenue.collectors.event_collector import LocalEventCollector
        collector = LocalEventCollector()
        assert collector._classify_event_type("스포츠") == "스포츠"

    def test_classify_event_type_unknown(self):
        from app.revenue.collectors.event_collector import LocalEventCollector
        collector = LocalEventCollector()
        assert collector._classify_event_type("기타분야") == "기타"

    def test_estimate_impact_very_high_for_olympics(self):
        from app.revenue.collectors.event_collector import LocalEventCollector
        collector = LocalEventCollector()
        item = {"title": "2026 국제박람회"}
        assert collector._estimate_impact(item) == "very_high"

    def test_estimate_impact_high_for_festival(self):
        from app.revenue.collectors.event_collector import LocalEventCollector
        collector = LocalEventCollector()
        item = {"title": "서울 페스티벌"}
        assert collector._estimate_impact(item) == "high"

    def test_estimate_impact_low_by_default(self):
        from app.revenue.collectors.event_collector import LocalEventCollector
        collector = LocalEventCollector()
        item = {"title": "동네 행사"}
        assert collector._estimate_impact(item) == "low"
