"""수요 예측 — Phase 1: 이동평균 기반 + 이벤트 가중치 + 계절성 보정"""

from datetime import date, timedelta

from app.revenue.crud import get_daily_metrics, get_events_for_date


class DemandForecaster:
    """
    Phase 1: 이동평균 기반 예측
    - 기본값: 최근 8주 동일 요일 평균
    - 이벤트 가중치: 이벤트 영향도에 따라 +5%~+30%
    - 계절성 보정: 성수기/비수기 지수
    """

    IMPACT_MULTIPLIERS = {
        "very_high": 1.30,
        "high": 1.20,
        "medium": 1.10,
        "low": 1.05,
    }

    SEASONAL_INDEX = {
        # 월별 계절성 지수 (1.0 = 평균)
        1: 0.75,
        2: 0.80,
        3: 0.90,
        4: 1.05,
        5: 1.10,
        6: 1.00,
        7: 1.30,
        8: 1.40,
        9: 1.10,
        10: 1.05,
        11: 0.85,
        12: 1.15,
    }

    def forecast(self, stay_date: date) -> dict:
        # 1. 과거 동일 요일 데이터 수집 (최근 8주)
        historical_occupancies = self._get_historical_same_weekday(stay_date, weeks=8)

        if len(historical_occupancies) < 4:
            # 데이터 부족 시 시장 평균으로 대체
            base_occ = 70.0
        else:
            import statistics

            base_occ = statistics.mean(historical_occupancies)

        # 2. 계절성 보정
        seasonal_factor = self.SEASONAL_INDEX.get(stay_date.month, 1.0)
        base_occ_adjusted = base_occ * seasonal_factor

        # 3. 이벤트 영향 적용
        events = get_events_for_date(stay_date)
        event_factor = 1.0
        if events:
            max_impact = max(
                self.IMPACT_MULTIPLIERS.get(e["impact_level"], 1.0) for e in events
            )
            event_factor = max_impact

        # 4. 3가지 시나리오 계산
        base = min(base_occ_adjusted * event_factor, 100)
        optimistic = min(base * 1.10, 100)
        pessimistic = max(base * 0.90, 0)

        return {
            "stay_date": stay_date,
            "forecast_date": date.today(),
            "predicted_occupancy_base": round(base, 1),
            "predicted_occupancy_opt": round(optimistic, 1),
            "predicted_occupancy_pess": round(pessimistic, 1),
            "factors": {
                "historical_avg": round(base_occ, 1),
                "seasonal_factor": seasonal_factor,
                "event_factor": event_factor,
                "events": [e["name"] for e in events],
            },
        }

    def _get_historical_same_weekday(self, target_date: date, weeks: int = 8) -> list[float]:
        """과거 N주의 동일 요일 점유율 데이터"""
        results = []
        for w in range(1, weeks + 1):
            past_date = target_date - timedelta(weeks=w)
            metrics = get_daily_metrics(past_date)
            if metrics:
                results.append(metrics["occupancy_rate"])
        return results
