"""경쟁사 요율 수집 — 초기: 수동 입력 API"""

import datetime as dt
from datetime import date


class ManualCompetitorRateCollector:
    """수동 입력으로 경쟁사 요율 관리"""

    def create_rate_entry(
        self,
        stay_date: date,
        competitor_name: str,
        rate_min: float | None,
        rate_max: float | None,
        is_soldout: bool = False,
        room_type: str | None = None,
        source: str = "manual",
    ) -> dict:
        return {
            "snapshot_date": dt.date.today(),
            "stay_date": stay_date,
            "competitor_name": competitor_name,
            "rate_min": rate_min,
            "rate_max": rate_max,
            "is_soldout": is_soldout,
            "room_type": room_type,
            "source": source,
        }
