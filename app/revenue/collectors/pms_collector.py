"""PMS REST API에서 일간 성과 지표 수집"""

from datetime import date

import httpx


class PMSCollector:
    """PMS REST API에서 일간 성과 지표 수집"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    async def collect_daily_metrics(self, target_date: date) -> dict:
        """PMS API에서 특정 날짜의 성과 지표 수집"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/reports/daily",
                params={"date": target_date.isoformat()},
                headers={"X-API-Key": self.api_key},
                timeout=30.0,
            )
            response.raise_for_status()
            raw = response.json()

        # PMS 응답 형식 → 내부 스키마 변환
        return {
            "report_date": target_date,
            "total_rooms": raw["property"]["total_rooms"],
            "occupied_rooms": raw["statistics"]["occupied"],
            "occupancy_rate": raw["statistics"]["occupancy_pct"],
            "adr": raw["statistics"]["adr"],
            "revpar": raw["statistics"]["revpar"],
            "total_revenue": raw["statistics"]["total_revenue"],
            "channel_breakdown": raw.get("channel_mix", {}),
            "ota_commission": raw.get("ota_commission_total", 0),
        }

    async def collect_pickup_data(self, stay_date: date, snapshot_date: date | None = None) -> dict:
        """특정 투숙일의 현재 예약 픽업 상황 수집"""
        snapshot_date = snapshot_date or date.today()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/reservations/pickup",
                params={
                    "stay_date": stay_date.isoformat(),
                    "as_of": snapshot_date.isoformat(),
                },
                headers={"X-API-Key": self.api_key},
            )
            raw = response.json()

        return {
            "stay_date": stay_date,
            "snapshot_date": snapshot_date,
            "confirmed_rooms": raw["confirmed_reservations"],
            "total_rooms": raw["total_rooms"],
            "pickup_rate": round(raw["confirmed_reservations"] / raw["total_rooms"] * 100, 2),
        }
