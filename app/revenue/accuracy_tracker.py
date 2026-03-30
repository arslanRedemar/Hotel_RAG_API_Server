"""예측 정확도 추적 — MAPE 계산 및 피드백 루프 (RM-F12)"""

import logging
from calendar import monthrange
from datetime import date

from app.revenue.crud import (
    get_daily_metrics_range,
    get_demand_forecasts_range,
    update_forecast_actual,
)

logger = logging.getLogger(__name__)


class ForecastAccuracyTracker:
    def calculate_monthly_mape(self, year: int, month: int) -> dict:
        """월별 예측 오차율(MAPE) 계산.

        목표: MAPE < 10%
        """
        _, last_day = monthrange(year, month)
        from_date = date(year, month, 1)
        to_date = date(year, month, last_day)

        forecasts = get_demand_forecasts_range(from_date, to_date)
        actuals = get_daily_metrics_range(from_date, to_date)

        actual_map = {m["report_date"]: m["occupancy_rate"] for m in actuals}

        errors = []
        for f in forecasts:
            actual = actual_map.get(f["stay_date"])
            predicted = f.get("predicted_occupancy_base")
            if actual and predicted:
                mape = abs(actual - predicted) / actual * 100
                errors.append(mape)
                update_forecast_actual(f["id"], actual, mape)

        overall_mape = sum(errors) / len(errors) if errors else None

        return {
            "year": year,
            "month": month,
            "mape_pct": round(overall_mape, 2) if overall_mape is not None else None,
            "sample_count": len(errors),
            "is_target_met": (overall_mape < 10.0) if overall_mape is not None else None,
        }
