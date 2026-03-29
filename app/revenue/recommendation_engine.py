"""AI 요율 권고 엔진 — LLM 기반"""

import json
import logging
from datetime import date, datetime

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.revenue.crud import (
    get_competitor_rates,
    get_current_pms_rate,
    get_demand_forecast,
    get_events_for_date,
    get_latest_pickup,
    get_daily_metrics,
    get_remaining_rooms,
    get_yoy_pickup,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

RATE_RECOMMENDATION_PROMPT = """
호텔 수익 관리 전문가로서 다음 데이터를 분석하여 {stay_date}의 객실 요율을 권고해주세요.

[내부 데이터]
- 현재 예약 픽업률: {current_pickup_pct}% (전년 동기: {yoy_pickup_pct}%)
- 잔여 객실: {remaining_rooms}실 (전체 {total_rooms}실)
- 작년 동일 날짜 실적: ADR {yoy_adr:,}원, 점유율 {yoy_occ}%
- 현재 요율: {current_rate:,}원

[시장 데이터]
- 경쟁사 A: {comp_a_rate}원 {comp_a_soldout}
- 경쟁사 B: {comp_b_rate}원 {comp_b_soldout}
- 경쟁사 C: {comp_c_rate}원 {comp_c_soldout}

[외부 신호]
- 주변 이벤트: {events}
- 날씨 예보: {weather}
- 공휴일: {holiday}

[수요 예측]
- 기준 시나리오 점유율: {forecast_base}%
- 낙관 시나리오: {forecast_opt}%
- 보수 시나리오: {forecast_pess}%

반드시 JSON으로만 응답:
{{
  "recommended_rate": 150000,
  "reasoning": "경쟁사 B 매진, 이벤트 D-3, 픽업 속도 전년비 150% → 인상 권고",
  "confidence": 0.88,
  "los_restriction": 2,
  "channel_suggestions": {{"ota": 40, "direct": 50, "gds": 10}},
  "urgency": "high"
}}
"""


class _LLMClient:
    """ChatOpenAI 래퍼 — Pydantic 모델이 아닌 일반 클래스로 patch.object 허용"""

    def __init__(self, model: str, temperature: float):
        self._chat = ChatOpenAI(model=model, temperature=temperature)

    def invoke(self, messages):
        return self._chat.invoke(messages)


class RateRecommendationEngine:
    def __init__(self):
        self.llm = _LLMClient("gpt-4o-mini", 0.1)

    async def recommend(self, stay_date: date) -> dict:
        # 데이터 수집
        context = self._gather_context(stay_date)

        prompt = RATE_RECOMMENDATION_PROMPT.format(
            stay_date=stay_date.isoformat(),
            **context,
        )

        response = self.llm.invoke([HumanMessage(content=prompt)])

        try:
            result = json.loads(response.content)
        except (json.JSONDecodeError, ValueError):
            logger.warning("LLM returned non-JSON response; using fallback")
            result = {
                "recommended_rate": context["current_rate"],
                "reasoning": "자동 분석 실패",
                "confidence": 0.0,
            }

        current_rate = context["current_rate"]
        recommended_rate = result["recommended_rate"]
        rate_change_pct = (
            round((recommended_rate - current_rate) / current_rate * 100, 1)
            if current_rate
            else 0.0
        )

        return {
            "recommendation_date": datetime.utcnow(),
            "stay_date": stay_date,
            "recommended_rate": recommended_rate,
            "current_rate": current_rate,
            "rate_change_pct": rate_change_pct,
            "reasoning": result.get("reasoning", ""),
            "confidence": result.get("confidence", 0.0),
            "los_restriction": result.get("los_restriction"),
        }

    def _gather_context(self, stay_date: date) -> dict:
        """권고에 필요한 모든 데이터 수집"""
        pickup = get_latest_pickup(stay_date)
        yoy_date = stay_date.replace(year=stay_date.year - 1)
        yoy_metrics = get_daily_metrics(yoy_date)
        competitor_rates = get_competitor_rates(stay_date)
        events = get_events_for_date(stay_date)
        forecast = get_demand_forecast(stay_date)

        return {
            "current_pickup_pct": pickup["pickup_rate"] if pickup else 0,
            "yoy_pickup_pct": get_yoy_pickup(stay_date),
            "remaining_rooms": get_remaining_rooms(stay_date),
            "total_rooms": settings.total_rooms,
            "yoy_adr": yoy_metrics["adr"] if yoy_metrics else 0,
            "yoy_occ": yoy_metrics["occupancy_rate"] if yoy_metrics else 0,
            "current_rate": get_current_pms_rate(stay_date),
            "comp_a_rate": competitor_rates[0]["rate_min"]
            if len(competitor_rates) > 0
            else "정보없음",
            "comp_a_soldout": "(매진)"
            if competitor_rates and competitor_rates[0]["is_soldout"]
            else "",
            "comp_b_rate": competitor_rates[1]["rate_min"]
            if len(competitor_rates) > 1
            else "정보없음",
            "comp_b_soldout": "(매진)"
            if len(competitor_rates) > 1 and competitor_rates[1]["is_soldout"]
            else "",
            "comp_c_rate": competitor_rates[2]["rate_min"]
            if len(competitor_rates) > 2
            else "정보없음",
            "comp_c_soldout": "(매진)"
            if len(competitor_rates) > 2 and competitor_rates[2]["is_soldout"]
            else "",
            "events": ", ".join(e["name"] for e in events) if events else "없음",
            "weather": self._get_weather_forecast(stay_date),
            "holiday": self._check_holiday(stay_date) or "해당없음",
            "forecast_base": forecast["predicted_occupancy_base"] if forecast else 0,
            "forecast_opt": forecast["predicted_occupancy_opt"] if forecast else 0,
            "forecast_pess": forecast["predicted_occupancy_pess"] if forecast else 0,
        }

    def _get_weather_forecast(self, stay_date: date) -> str:
        """날씨 예보 (미구현: 외부 API 연동 필요)"""
        return "정보없음"

    def _check_holiday(self, stay_date: date) -> str | None:
        """공휴일 확인 (미구현: 공공 API 연동 필요)"""
        return None
