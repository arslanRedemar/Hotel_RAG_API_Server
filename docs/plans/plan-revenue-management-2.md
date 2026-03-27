# Plan: Revenue Management — 데이터 파이프라인 / 예측 모델 상세

> **상위 문서**: [plan-revenue-management.md](./plan-revenue-management.md)
> **내용**: 수요 예측 모델, 경쟁사 요율 수집, 피드백 루프

---

## 1. 데이터 수집 파이프라인

### 1-1. 경쟁사 요율 수집 전략

직접 OTA 스크래핑은 이용약관 위반 가능성이 있으므로 아래 3가지 방법 중 선택:

| 방법 | 비용 | 정확도 | 적법성 |
|------|------|--------|--------|
| **OTA 파트너 데이터 피드** | 중간 | 높음 | 적법 ✅ |
| **STR/RateGain API** | 높음 | 매우 높음 | 적법 ✅ |
| **수동 입력 (초기)** | 없음 | 낮음 | 적법 ✅ |
| OTA 직접 스크래핑 | 없음 | 중간 | 회색지대 ⚠️ |

**초기 구현**: 수동 입력 API + OTA 파트너 피드 연동 준비.

```python
# app/revenue/collectors/competitor_collector.py

class ManualCompetitorRateAPI:
    """초기 단계: 수동 입력으로 경쟁사 요율 관리"""
    pass

class RateGainCollector:
    """RateGain API 연동 (향후 전환)"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.rategain.com/v2"

    async def collect_rates(self, check_in: date, competitors: list[str]) -> list[dict]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/competitive-rates",
                params={
                    "check_in": check_in.isoformat(),
                    "check_out": (check_in + timedelta(days=1)).isoformat(),
                    "competitors": ",".join(competitors)
                },
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            data = response.json()

        rates = []
        for competitor in data.get("competitors", []):
            rates.append({
                "snapshot_date": date.today(),
                "stay_date": check_in,
                "competitor_name": competitor["name"],
                "rate_min": competitor.get("min_rate"),
                "rate_max": competitor.get("max_rate"),
                "is_soldout": competitor.get("availability") == 0,
            })
        return rates
```

### 1-2. 이벤트 데이터 수집

```python
# app/revenue/collectors/event_collector.py

class LocalEventCollector:
    """로컬 이벤트 데이터 수집 (공공 API 또는 수동 입력)"""

    async def fetch_from_korea_culture_api(self, from_date: date, to_date: date) -> list[dict]:
        """문화체육관광부 공공 API 활용"""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "http://api.kcisa.kr/openapi/service/rest/EventInfo/getList",
                params={
                    "serviceKey": settings.culture_api_key,
                    "startDate": from_date.strftime("%Y%m%d"),
                    "endDate": to_date.strftime("%Y%m%d"),
                    "sido": "서울",
                }
            )

        # XML 파싱 (공공 API는 XML 반환)
        import xmltodict
        data = xmltodict.parse(response.text)
        items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])

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

    def _classify_event_type(self, realm: str) -> str:
        mapping = {
            "음악": "콘서트", "공연": "공연", "전시": "전시",
            "스포츠": "스포츠", "컨벤션": "컨퍼런스"
        }
        for key, val in mapping.items():
            if realm and key in realm:
                return val
        return "기타"

    def _estimate_impact(self, item: dict) -> str:
        """이벤트 규모에 따른 영향도 추정"""
        name = item.get("title", "")
        # 대형 이벤트 키워드
        if any(kw in name for kw in ["월드컵", "올림픽", "국제", "박람회"]):
            return "very_high"
        elif any(kw in name for kw in ["페스티벌", "축제", "콘서트"]):
            return "high"
        elif any(kw in name for kw in ["전시", "세미나", "컨퍼런스"]):
            return "medium"
        return "low"
```

---

## 2. 수요 예측 모델

### 2-1. 예측 방법론

초기는 통계 기반 모델, 데이터 축적 후 ML 모델로 전환.

**단계별 모델:**
```
Phase 1 (초기): 이동평균 + 이벤트 가중치 (단순, 즉시 구현 가능)
Phase 2 (3개월 데이터 이상): Prophet (페이스북 시계열 예측)
Phase 3 (1년 데이터 이상): XGBoost + 외부 신호 결합
```

```python
# app/revenue/demand_forecaster.py

from datetime import date, timedelta
import numpy as np

class DemandForecaster:
    """
    Phase 1: 이동평균 기반 예측
    - 기본값: 최근 4주 동일 요일 평균
    - 이벤트 가중치: 이벤트 영향도에 따라 +10%~+30%
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
        1: 0.75, 2: 0.80, 3: 0.90, 4: 1.05,
        5: 1.10, 6: 1.00, 7: 1.30, 8: 1.40,
        9: 1.10, 10: 1.05, 11: 0.85, 12: 1.15
    }

    def forecast(self, stay_date: date) -> dict:
        # 1. 과거 동일 요일 데이터 수집 (최근 8주)
        historical_occupancies = self._get_historical_same_weekday(stay_date, weeks=8)

        if len(historical_occupancies) < 4:
            # 데이터 부족 시 시장 평균으로 대체
            base_occ = 70.0
        else:
            base_occ = np.mean(historical_occupancies)

        # 2. 계절성 보정
        seasonal_factor = self.SEASONAL_INDEX.get(stay_date.month, 1.0)
        base_occ_adjusted = base_occ * seasonal_factor

        # 3. 이벤트 영향 적용
        events = get_events_for_date(stay_date)
        event_factor = 1.0
        if events:
            max_impact = max(self.IMPACT_MULTIPLIERS.get(e["impact_level"], 1.0) for e in events)
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
                "events": [e["name"] for e in events]
            }
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


class ProphetForecaster:
    """Phase 2: Facebook Prophet 기반 예측 (3개월 데이터 이상 필요)"""

    def train_and_forecast(self, forecast_days: int = 90) -> list[dict]:
        from prophet import Prophet
        import pandas as pd

        # 학습 데이터 준비
        metrics = get_all_daily_metrics()
        df = pd.DataFrame([
            {"ds": m["report_date"], "y": m["occupancy_rate"]}
            for m in metrics
        ])

        # Prophet 모델 학습
        model = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=True,
            daily_seasonality=False,
            seasonality_mode='multiplicative'
        )

        # 이벤트 추가 (외부 신호)
        events = get_all_events()
        for event in events:
            model.add_regressor(f"event_{event['id']}")

        model.fit(df)

        # 미래 예측
        future = model.make_future_dataframe(periods=forecast_days)
        forecast = model.predict(future)

        return [
            {
                "stay_date": row["ds"].date(),
                "predicted_occupancy_base": round(row["yhat"], 1),
                "predicted_occupancy_opt": round(row["yhat_upper"], 1),
                "predicted_occupancy_pess": round(row["yhat_lower"], 1),
            }
            for _, row in forecast.tail(forecast_days).iterrows()
        ]
```

---

## 3. 피드백 루프 및 모델 정확도 추적 (RM-F12)

### 3-1. MAPE 계산

```python
# app/revenue/accuracy_tracker.py

class ForecastAccuracyTracker:
    def calculate_monthly_mape(self, year: int, month: int) -> dict:
        """월별 예측 오차율(MAPE) 계산"""
        from calendar import monthrange

        _, last_day = monthrange(year, month)
        from_date = date(year, month, 1)
        to_date = date(year, month, last_day)

        # 예측값과 실적값 매핑
        forecasts = get_demand_forecasts_range(from_date, to_date)
        actuals = get_daily_metrics_range(from_date, to_date)

        actual_map = {m["report_date"]: m["occupancy_rate"] for m in actuals}

        errors = []
        for f in forecasts:
            actual = actual_map.get(f["stay_date"])
            if actual and f["predicted_occupancy_base"]:
                mape = abs(actual - f["predicted_occupancy_base"]) / actual * 100
                errors.append(mape)

                # 예측 레코드에 실적 업데이트
                update_forecast_actual(f["id"], actual, mape)

        overall_mape = sum(errors) / len(errors) if errors else None

        return {
            "year": year,
            "month": month,
            "mape_pct": round(overall_mape, 2) if overall_mape else None,
            "sample_count": len(errors),
            "is_target_met": overall_mape < 10.0 if overall_mape else None  # 목표: 10% 이하
        }
```

### 3-2. AI 권고 실효성 추적

```python
# app/revenue/feedback_tracker.py

class RecommendationEffectivenessTracker:
    def analyze_period(self, from_date: date, to_date: date) -> dict:
        """권고 기간의 실효성 분석"""
        recs = get_recommendations_range(from_date, to_date)

        accepted = [r for r in recs if r["action_taken"] == "accepted"]
        rejected = [r for r in recs if r["action_taken"] == "rejected"]
        total = len([r for r in recs if r["action_taken"] != "pending"])

        # 수락 케이스: 권고 요율 적용 후 실제 점유율이 예측과 일치했는지
        accept_outcomes = []
        for rec in accepted:
            actual_metrics = get_daily_metrics(rec["stay_date"])
            if actual_metrics:
                expected_rev = rec["recommended_rate"] * (actual_metrics["occupancy_rate"] / 100) * settings.total_rooms
                actual_rev = actual_metrics["total_revenue"] / settings.total_rooms  # RevPAR
                accept_outcomes.append({
                    "stay_date": rec["stay_date"],
                    "recommended_rate": rec["recommended_rate"],
                    "actual_occupancy": actual_metrics["occupancy_rate"],
                    "outcome_positive": actual_rev >= rec["recommended_rate"] * 0.7  # 70% 점유 이상 시 성공
                })

        return {
            "period": f"{from_date} ~ {to_date}",
            "total_recommendations": total,
            "accept_count": len(accepted),
            "reject_count": len(rejected),
            "accept_rate_pct": round(len(accepted) / total * 100, 1) if total else 0,
            "positive_outcomes": sum(1 for o in accept_outcomes if o["outcome_positive"]),
            "positive_outcome_rate_pct": round(
                sum(1 for o in accept_outcomes if o["outcome_positive"]) / len(accept_outcomes) * 100, 1
            ) if accept_outcomes else 0,
        }
```

---

## 4. 픽업 속도 시각화 (RM-F05)

```python
# app/api/routes/revenue.py

@router.get("/revenue/pickup-pace/{stay_date}")
async def get_pickup_pace(
    stay_date: date,
    current_user: User = Depends(require_revenue_manager)
):
    """
    특정 투숙일의 예약 픽업 속도를 과거 동일 기간 대비 시각화용 데이터
    X축: 투숙일까지 남은 일수 (D-90 ~ D-0)
    Y축: 해당 시점의 점유율 (%)
    """
    today = date.today()
    days_to_stay = (stay_date - today).days

    # 현재 픽업 데이터 (D-일수별 누적)
    current_pickups = get_pickup_snapshots(stay_date)

    # 작년 동일 날짜 픽업 데이터 (비교용)
    yoy_stay_date = stay_date.replace(year=stay_date.year - 1)
    yoy_pickups = get_pickup_snapshots(yoy_stay_date)

    return {
        "stay_date": stay_date,
        "days_to_stay": days_to_stay,
        "current_series": [
            {"days_before": (stay_date - s["snapshot_date"]).days, "occupancy_pct": s["pickup_rate"]}
            for s in current_pickups
        ],
        "yoy_series": [
            {"days_before": (yoy_stay_date - s["snapshot_date"]).days, "occupancy_pct": s["pickup_rate"]}
            for s in yoy_pickups
        ],
        "current_vs_yoy_delta": (
            current_pickups[-1]["pickup_rate"] - yoy_pickups[-1]["pickup_rate"]
            if current_pickups and yoy_pickups else None
        )
    }
```

---

## 5. 추가 의존성

```
# requirements.txt
prophet>=1.1.5          # 시계열 예측 (Phase 2)
scikit-learn>=1.4.0     # ML 유틸리티
pandas>=2.1.0           # 데이터 처리
numpy>=1.26.0           # 수치 계산
httpx>=0.27.0           # 비동기 HTTP (이미 있음)
xmltodict>=0.13.0       # 공공 API XML 파싱
```

---

## 6. PMS 미연동 시 대안: 수동 데이터 입력 API

```python
# app/api/routes/revenue.py

@router.post("/revenue/metrics/manual")
async def input_daily_metrics_manually(
    data: DailyMetricsCreate,
    current_user: User = Depends(require_revenue_manager)
):
    """
    PMS 연동 전 수동으로 일간 성과 지표 입력
    DailyMetricsCreate:
    - report_date: date
    - occupied_rooms: int
    - total_rooms: int
    - total_revenue: float
    - channel_breakdown: dict (optional)
    """
    occupancy_rate = round(data.occupied_rooms / data.total_rooms * 100, 2)
    adr = round(data.total_revenue / data.occupied_rooms, 2) if data.occupied_rooms else 0
    revpar = round(data.total_revenue / data.total_rooms, 2)

    return save_daily_metrics({
        **data.dict(),
        "occupancy_rate": occupancy_rate,
        "adr": adr,
        "revpar": revpar,
    })

@router.post("/revenue/competitor-rates/manual")
async def input_competitor_rates_manually(
    rates: list[CompetitorRateCreate],
    current_user: User = Depends(require_revenue_manager)
):
    """수동으로 경쟁사 요율 입력"""
    saved = [save_competitor_rate(r.dict()) for r in rates]
    return {"saved_count": len(saved)}
```
