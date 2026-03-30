"""로컬 이벤트 데이터 수집 (공공 API 또는 수동 입력)"""

from datetime import date


class LocalEventCollector:
    """로컬 이벤트 데이터 수집 (공공 API 또는 수동 입력)"""

    async def fetch_from_korea_culture_api(self, from_date: date, to_date: date) -> list[dict]:
        """문화체육관광부 공공 API 활용"""
        import httpx

        from app.core.config import settings

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "http://api.kcisa.kr/openapi/service/rest/EventInfo/getList",
                params={
                    "serviceKey": getattr(settings, "culture_api_key", ""),
                    "startDate": from_date.strftime("%Y%m%d"),
                    "endDate": to_date.strftime("%Y%m%d"),
                    "sido": "서울",
                },
            )

        # XML 파싱 (공공 API는 XML 반환)
        import xmltodict

        data = xmltodict.parse(response.text)
        items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]

        return [
            {
                "name": item.get("title"),
                "type": self._classify_event_type(item.get("realmName")),
                "start_date": item.get("startDate"),
                "end_date": item.get("endDate"),
                "venue": item.get("place"),
                "impact_level": self._estimate_impact(item),
            }
            for item in items
        ]

    def _classify_event_type(self, realm: str | None) -> str:
        mapping = {
            "음악": "콘서트",
            "공연": "공연",
            "전시": "전시",
            "스포츠": "스포츠",
            "컨벤션": "컨퍼런스",
        }
        for key, val in mapping.items():
            if realm and key in realm:
                return val
        return "기타"

    def _estimate_impact(self, item: dict) -> str:
        """이벤트 규모에 따른 영향도 추정"""
        name = item.get("title", "")
        if any(kw in name for kw in ["월드컵", "올림픽", "국제", "박람회"]):
            return "very_high"
        elif any(kw in name for kw in ["페스티벌", "축제", "콘서트"]):
            return "high"
        elif any(kw in name for kw in ["전시", "세미나", "컨퍼런스"]):
            return "medium"
        return "low"
