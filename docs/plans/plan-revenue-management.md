# Plan: Revenue Management Support 구현 계획

> **요구사항 참조**: [revenue_management.md](../requirements/revenue_management.md)
> **우선순위**: P2
> **관련 하위 문서**:
> - [plan-revenue-management-2.md](./plan-revenue-management-2.md) — 데이터 파이프라인 / 예측 모델 상세

---

## 1. 현재 상태

Revenue Management 관련 코드 없음. P2 우선순위로 Phase 1~3 완료 후 구현.

---

## 2. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                Revenue Management 시스템                      │
│                                                              │
│  데이터 수집 레이어                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │PMS 연동  │  │OTA 요율  │  │이벤트    │  │날씨 API   │  │
│  │(일간 배치)│  │(스크래핑)│  │캘린더   │  │           │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬──────┘  │
│       └─────────────┴──────────────┴──────────────┘         │
│                              │                               │
│  ┌───────────────────────────▼──────────────────────────┐   │
│  │              데이터 통합 레이어 (DWH)                  │   │
│  │  MySQL: metrics, competitor_rates, events, weather   │   │
│  └───────────────────────────┬──────────────────────────┘   │
│                              │                               │
│  ┌───────────────────────────▼──────────────────────────┐   │
│  │              AI 분석 레이어                            │   │
│  │  - 수요 예측 (30/60/90일)                             │   │
│  │  - 요율 권고 엔진                                     │   │
│  │  - 단체 예약 시뮬레이터                               │   │
│  └───────────────────────────┬──────────────────────────┘   │
│                              │                               │
│  ┌───────────────────────────▼──────────────────────────┐   │
│  │              대시보드 API                              │   │
│  │  RevPAR / ADR / 점유율 / 채널 믹스                   │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. DB 스키마

```sql
-- 일간 성과 지표 (PMS에서 수집)
CREATE TABLE daily_metrics (
    id              INT      PRIMARY KEY AUTO_INCREMENT,
    report_date     DATE     NOT NULL UNIQUE,
    total_rooms     INT      NOT NULL,
    occupied_rooms  INT      NOT NULL,
    occupancy_rate  DECIMAL(5,2) NOT NULL,    -- 점유율 (%)
    adr             DECIMAL(10,2) NOT NULL,   -- Average Daily Rate (원)
    revpar          DECIMAL(10,2) NOT NULL,   -- Revenue Per Available Room
    total_revenue   DECIMAL(15,2) NOT NULL,
    channel_breakdown JSON,                    -- {"ota": 45, "direct": 30, "gds": 25} (%)
    ota_commission  DECIMAL(15,2),            -- 당일 OTA 수수료 합계
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_report_date (report_date)
);

-- 예약 픽업 이력 (수요 예측용)
CREATE TABLE reservation_pickups (
    id              INT      PRIMARY KEY AUTO_INCREMENT,
    stay_date       DATE     NOT NULL,         -- 투숙일
    snapshot_date   DATE     NOT NULL,         -- 측정일
    confirmed_rooms INT      NOT NULL,         -- 확정 예약 객실 수
    total_rooms     INT      NOT NULL,         -- 전체 객실 수
    pickup_rate     DECIMAL(5,2) NOT NULL,     -- 점유율 (%)
    UNIQUE KEY uq_stay_snapshot (stay_date, snapshot_date),
    INDEX idx_stay_date (stay_date)
);

-- 경쟁사 요율 (일간 수집)
CREATE TABLE competitor_rates (
    id              INT      PRIMARY KEY AUTO_INCREMENT,
    snapshot_date   DATE     NOT NULL,
    stay_date       DATE     NOT NULL,
    competitor_name VARCHAR(100) NOT NULL,
    rate_min        DECIMAL(10,2),            -- 최저 요율
    rate_max        DECIMAL(10,2),            -- 최고 요율
    is_soldout      BOOLEAN  NOT NULL DEFAULT FALSE,
    room_type       VARCHAR(100),
    source          VARCHAR(50),              -- OTA 소스
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_stay_date (stay_date),
    INDEX idx_snapshot (snapshot_date)
);

-- 로컬 이벤트
CREATE TABLE local_events (
    id          INT      PRIMARY KEY AUTO_INCREMENT,
    name        VARCHAR(300) NOT NULL,
    type        VARCHAR(50),                  -- '콘서트', '스포츠', '전시', '컨퍼런스'
    start_date  DATE     NOT NULL,
    end_date    DATE     NOT NULL,
    venue       VARCHAR(200),
    expected_attendance INT,
    impact_level ENUM('low','medium','high','very_high') NOT NULL DEFAULT 'medium',
    source      VARCHAR(100),
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_start_date (start_date)
);

-- AI 요율 권고
CREATE TABLE rate_recommendations (
    id              INT      PRIMARY KEY AUTO_INCREMENT,
    recommendation_date DATETIME NOT NULL,
    stay_date       DATE     NOT NULL,
    recommended_rate DECIMAL(10,2) NOT NULL,
    current_rate    DECIMAL(10,2),
    rate_change_pct DECIMAL(5,2),            -- 변경률 (%)
    reasoning       TEXT     NOT NULL,        -- 권고 근거
    confidence      DECIMAL(4,3),
    los_restriction INT,                     -- 최소 투숙일 권고
    action_taken    ENUM('accepted','modified','rejected','pending') NOT NULL DEFAULT 'pending',
    actual_rate_applied DECIMAL(10,2),
    decided_by      INT REFERENCES users(id),
    decided_at      DATETIME,
    rejection_reason TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_stay_date (stay_date),
    INDEX idx_action (action_taken)
);

-- 수요 예측 결과
CREATE TABLE demand_forecasts (
    id              INT      PRIMARY KEY AUTO_INCREMENT,
    forecast_date   DATETIME NOT NULL,        -- 예측 실행 시점
    stay_date       DATE     NOT NULL,
    predicted_occupancy_base DECIMAL(5,2),   -- 기준 시나리오
    predicted_occupancy_opt  DECIMAL(5,2),   -- 낙관 시나리오
    predicted_occupancy_pess DECIMAL(5,2),   -- 보수 시나리오
    actual_occupancy DECIMAL(5,2),           -- 실적 (나중에 업데이트)
    mape            DECIMAL(5,2),            -- 예측 오차율
    UNIQUE KEY uq_forecast_stay (forecast_date, stay_date),
    INDEX idx_stay_date (stay_date)
);

-- 단체 예약 시뮬레이션 이력
CREATE TABLE group_booking_simulations (
    id              INT      PRIMARY KEY AUTO_INCREMENT,
    rooms_requested INT      NOT NULL,
    check_in        DATE     NOT NULL,
    check_out       DATE     NOT NULL,
    proposed_rate   DECIMAL(10,2) NOT NULL,
    simulated_accept_revenue  DECIMAL(15,2),
    simulated_reject_revenue  DECIMAL(15,2),
    opportunity_cost DECIMAL(15,2),
    recommendation  ENUM('accept','reject','negotiate') NOT NULL,
    recommendation_note TEXT,
    created_by      INT REFERENCES users(id),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. 구현 단계

### Phase 1 — 데이터 수집 파이프라인

> 상세: [plan-revenue-management-2.md](./plan-revenue-management-2.md#1-데이터-수집-파이프라인)

#### 4-1. PMS 연동 (RM-F01)

```python
# app/revenue/collectors/pms_collector.py

from datetime import date, timedelta
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
                timeout=30.0
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

    async def collect_pickup_data(self, stay_date: date, snapshot_date: date = None) -> dict:
        """특정 투숙일의 현재 예약 픽업 상황 수집"""
        snapshot_date = snapshot_date or date.today()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/reservations/pickup",
                params={
                    "stay_date": stay_date.isoformat(),
                    "as_of": snapshot_date.isoformat()
                },
                headers={"X-API-Key": self.api_key}
            )
            raw = response.json()

        return {
            "stay_date": stay_date,
            "snapshot_date": snapshot_date,
            "confirmed_rooms": raw["confirmed_reservations"],
            "total_rooms": raw["total_rooms"],
            "pickup_rate": round(raw["confirmed_reservations"] / raw["total_rooms"] * 100, 2)
        }
```

#### 4-2. 데이터 수집 스케줄 (Celery Beat)

```python
# app/tasks/revenue_tasks.py

celery_app.conf.beat_schedule.update({
    # 매시간: PMS 성과 지표 수집 (RM-F01: 1시간 단위)
    'collect-hourly-pms-metrics': {
        'task': 'app.tasks.revenue_tasks.collect_hourly_pms_metrics',
        'schedule': crontab(minute=0),  # 매 정시
    },
    # 매일 오전 7시: 경쟁사 요율 수집
    'collect-competitor-rates': {
        'task': 'app.tasks.revenue_tasks.collect_competitor_rates',
        'schedule': crontab(hour=7, minute=0),
    },
    # 매일 오전 6시: 30일 이내 수요 예측 업데이트
    'update-demand-forecasts': {
        'task': 'app.tasks.revenue_tasks.update_demand_forecasts',
        'schedule': crontab(hour=6, minute=0),
    },
    # 매일 오전 8시: AI 요율 권고 생성
    'generate-rate-recommendations': {
        'task': 'app.tasks.revenue_tasks.generate_rate_recommendations',
        'schedule': crontab(hour=8, minute=0),
    },
})

@celery_app.task
async def collect_hourly_pms_metrics():
    target = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    collector = PMSCollector(settings.pms_base_url, settings.pms_api_key)
    metrics = await collector.collect_daily_metrics(target.date())
    save_daily_metrics(metrics)

@celery_app.task
async def generate_rate_recommendations():
    """향후 30일 각 날짜에 대한 요율 권고 생성"""
    engine = RateRecommendationEngine()
    today = date.today()

    for day_offset in range(1, 31):
        stay_date = today + timedelta(days=day_offset)
        recommendation = await engine.recommend(stay_date)
        save_recommendation(recommendation)
```

---

### Phase 2 — 요율 권고 엔진 (RM-F20~22)

```python
# app/revenue/recommendation_engine.py

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
import json

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

class RateRecommendationEngine:
    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)

    async def recommend(self, stay_date: date) -> dict:
        # 데이터 수집
        context = await self._gather_context(stay_date)

        prompt = RATE_RECOMMENDATION_PROMPT.format(
            stay_date=stay_date.isoformat(),
            **context
        )

        response = self.llm.invoke([HumanMessage(content=prompt)])

        try:
            result = json.loads(response.content)
        except json.JSONDecodeError:
            result = {"recommended_rate": context["current_rate"], "reasoning": "자동 분석 실패", "confidence": 0.0}

        return {
            "recommendation_date": datetime.utcnow(),
            "stay_date": stay_date,
            "recommended_rate": result["recommended_rate"],
            "current_rate": context["current_rate"],
            "rate_change_pct": round((result["recommended_rate"] - context["current_rate"]) / context["current_rate"] * 100, 1),
            "reasoning": result["reasoning"],
            "confidence": result.get("confidence", 0.0),
            "los_restriction": result.get("los_restriction"),
        }

    async def _gather_context(self, stay_date: date) -> dict:
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
            "current_rate": await get_current_pms_rate(stay_date),
            "comp_a_rate": competitor_rates[0]["rate_min"] if len(competitor_rates) > 0 else "정보없음",
            "comp_a_soldout": "(매진)" if competitor_rates and competitor_rates[0]["is_soldout"] else "",
            "comp_b_rate": competitor_rates[1]["rate_min"] if len(competitor_rates) > 1 else "정보없음",
            "comp_b_soldout": "(매진)" if len(competitor_rates) > 1 and competitor_rates[1]["is_soldout"] else "",
            "comp_c_rate": competitor_rates[2]["rate_min"] if len(competitor_rates) > 2 else "정보없음",
            "comp_c_soldout": "(매진)" if len(competitor_rates) > 2 and competitor_rates[2]["is_soldout"] else "",
            "events": ", ".join(e["name"] for e in events) if events else "없음",
            "weather": get_weather_forecast(stay_date),
            "holiday": check_holiday(stay_date) or "해당없음",
            "forecast_base": forecast["predicted_occupancy_base"] if forecast else 0,
            "forecast_opt": forecast["predicted_occupancy_opt"] if forecast else 0,
            "forecast_pess": forecast["predicted_occupancy_pess"] if forecast else 0,
        }
```

---

### Phase 3 — 단체 예약 시뮬레이터 (RM-F30~31)

```python
# app/revenue/group_simulator.py

class GroupBookingSimulator:
    def simulate(
        self,
        rooms_requested: int,
        check_in: date,
        check_out: date,
        proposed_rate: float
    ) -> dict:
        nights = (check_out - check_in).days
        total_room_nights = rooms_requested * nights

        # 시나리오 1: 단체 수락
        accept_revenue = proposed_rate * total_room_nights

        # 시나리오 2: 단체 거절 시 개별 예약으로 채울 경우
        reject_revenue = 0
        opportunity_breakdown = []

        for day_offset in range(nights):
            stay_date = check_in + timedelta(days=day_offset)
            forecast = get_demand_forecast(stay_date)
            base_rate = get_current_pms_rate(stay_date)

            expected_occ = (forecast["predicted_occupancy_base"] if forecast else 70) / 100
            expected_fill = min(rooms_requested, int(rooms_requested * expected_occ))
            day_revenue = expected_fill * base_rate

            reject_revenue += day_revenue
            opportunity_breakdown.append({
                "date": stay_date.isoformat(),
                "expected_fill": expected_fill,
                "rate": base_rate,
                "revenue": day_revenue,
            })

        opportunity_cost = accept_revenue - reject_revenue

        # 권고 결정
        if accept_revenue > reject_revenue * 1.05:  # 단체가 5% 이상 유리
            recommendation = "accept"
            note = f"단체 수락 시 확정 수익 {accept_revenue:,.0f}원이 개별 예약 기대치({reject_revenue:,.0f}원)보다 {(accept_revenue/reject_revenue-1)*100:.0f}% 유리합니다."
        elif accept_revenue < reject_revenue * 0.85:  # 단체가 15% 이상 불리
            recommendation = "reject"
            note = f"개별 예약 기대 수익({reject_revenue:,.0f}원)이 단체 수익({accept_revenue:,.0f}원)보다 높습니다. 거절 권고."
        else:
            recommendation = "negotiate"
            note = f"수익 차이가 미미합니다. 취소 패널티 강화 또는 F&B 마진 재협상 조건으로 수락을 고려하세요."

        return {
            "accept_revenue": accept_revenue,
            "reject_revenue": reject_revenue,
            "opportunity_cost": opportunity_cost,
            "recommendation": recommendation,
            "recommendation_note": note,
            "nights": nights,
            "total_room_nights": total_room_nights,
            "daily_breakdown": opportunity_breakdown,
        }
```

---

### Phase 4 — 성과 대시보드 API (RM-F40~41)

```python
# app/api/routes/revenue.py

@router.get("/revenue/dashboard")
async def get_dashboard(
    period: str = "daily",      # daily | weekly | monthly
    from_date: date = None,
    to_date: date = None,
    current_user: User = Depends(require_revenue_manager)
):
    """RevPAR, ADR, 점유율, 채널 믹스 대시보드"""
    if not to_date:
        to_date = date.today()
    if not from_date:
        from_date = to_date - timedelta(days=30 if period == "daily" else 365)

    metrics = get_daily_metrics_range(from_date, to_date)

    # 집계
    summary = {
        "revpar_avg": sum(m["revpar"] for m in metrics) / len(metrics) if metrics else 0,
        "adr_avg": sum(m["adr"] for m in metrics) / len(metrics) if metrics else 0,
        "occupancy_avg": sum(m["occupancy_rate"] for m in metrics) / len(metrics) if metrics else 0,
        "total_revenue": sum(m["total_revenue"] for m in metrics),
        "total_ota_commission": sum(m["ota_commission"] or 0 for m in metrics),
    }

    # 채널 믹스 평균
    channel_totals = defaultdict(float)
    for m in metrics:
        if m.get("channel_breakdown"):
            for channel, pct in m["channel_breakdown"].items():
                channel_totals[channel] += pct
    channel_avg = {k: round(v / len(metrics), 1) for k, v in channel_totals.items()}

    # 오늘의 AI 요율 권고
    today_recommendations = get_recommendations(
        from_date=date.today(),
        to_date=date.today() + timedelta(days=14),
        status="pending"
    )

    return {
        "summary": summary,
        "channel_mix": channel_avg,
        "time_series": metrics,
        "pending_recommendations": today_recommendations,
    }

@router.post("/revenue/recommendations/{rec_id}/decide")
async def decide_recommendation(
    rec_id: int,
    action: Literal["accepted", "modified", "rejected"],
    actual_rate: float = None,
    rejection_reason: str = None,
    current_user: User = Depends(require_revenue_manager)
):
    """AI 요율 권고 수락/수정/거절"""
    update_recommendation(rec_id, {
        "action_taken": action,
        "actual_rate_applied": actual_rate,
        "rejection_reason": rejection_reason,
        "decided_by": current_user.id,
        "decided_at": datetime.utcnow()
    })
    return {"status": "ok"}
```

---

## 5. Revenue Dashboard UI

```
/revenue                          # 대시보드 메인 (Revenue Manager+)
/revenue/recommendations          # AI 요율 권고 목록
/revenue/forecast                 # 수요 예측 차트
/revenue/group-simulator          # 단체 예약 시뮬레이터
/revenue/competitor               # 경쟁사 요율 비교
```

### 대시보드 레이아웃

```
┌──────────────────────────────────────────────────────────┐
│  수익 관리 대시보드                          [기간: 이번달]│
├─────────────┬─────────────┬─────────────┬────────────────┤
│  RevPAR     │    ADR      │  점유율     │  OTA 수수료    │
│  ₩87,500    │  ₩125,000  │  70.0%      │  ₩3,200,000   │
│  ▲5.2% YoY │  ▲3.1% YoY │  ▲2.3%p    │  채널비: 15%  │
├─────────────┴─────────────┴─────────────┴────────────────┤
│  향후 14일 AI 권고 요율                                   │
│  ┌───────────┬────────────┬──────────┬──────────────────┐│
│  │   날짜    │ 현재 요율  │ 권고 요율│    근거          ││
│  ├───────────┼────────────┼──────────┼──────────────────┤│
│  │ 3/28 (토) │ ₩120,000  │₩160,000 │ 이벤트, 경쟁사 A │││
│  │           │            │+33%      │ 매진              ││
│  │           │            │          │ [수락] [수정] [거절]│
│  ├───────────┼────────────┼──────────┼──────────────────┤│
│  │ 3/29 (일) │ ₩110,000  │₩110,000 │ 변경 불필요       ││
│  └───────────┴────────────┴──────────┴──────────────────┘│
├──────────────────────────────────────────────────────────┤
│  채널 믹스                │  예약 픽업 추이              │
│  ████ OTA    45%          │  ╭──────╮                    │
│  ████ 직접   38%          │ ╭╯      ╰──╮  ── 올해       │
│  ████ GDS    17%          │╭╯          ╰── ── 작년       │
└──────────────────────────────────────────────────────────┘
```

---

## 6. 파일 구조

```
app/
├── revenue/                        # 신규 모듈
│   ├── __init__.py
│   ├── collectors/
│   │   ├── pms_collector.py        # PMS 연동
│   │   ├── competitor_collector.py # 경쟁사 요율 수집
│   │   └── event_collector.py      # 이벤트 캘린더
│   ├── recommendation_engine.py    # AI 요율 권고
│   ├── demand_forecaster.py        # 수요 예측
│   └── group_simulator.py          # 단체 예약 시뮬레이터
│
├── api/routes/
│   └── revenue.py                  # Revenue API 엔드포인트
│
└── tasks/
    └── revenue_tasks.py            # Celery 데이터 수집/예측 태스크
```

---

## 7. 구현 체크리스트

### Phase 1 (데이터 수집)
- [x] `daily_metrics`, `competitor_rates`, `local_events` 테이블 생성 (`app/database/models.py`)
- [x] `reservation_pickups` 테이블 생성
- [x] `PMSCollector` 구현 (`app/revenue/collectors/pms_collector.py`)
- [x] 경쟁사 요율 수집기 구현 (`app/revenue/collectors/competitor_collector.py`)
- [x] 이벤트 수집기 구현 (`app/revenue/collectors/event_collector.py`)
- [x] Celery Beat 스케줄 등록 (`app/tasks/revenue_tasks.py` — 06:00 예측, 08:00 권고)
- [x] 일간 성과 지표 수동 입력 API `POST /revenue/metrics`

### Phase 2 (AI 분석)
- [x] `demand_forecasts` 테이블 생성
- [x] `DemandForecaster` 구현 (`app/revenue/demand_forecaster.py` — 이동평균 + 이벤트 가중치 + 계절성)
- [x] `rate_recommendations` 테이블 생성
- [x] `RateRecommendationEngine` 구현 (`app/revenue/recommendation_engine.py` — GPT-4o-mini 기반)
- [x] `generate_forecasts_task` Celery 태스크 (멱등성 보장, DB 주입 가능)
- [x] `generate_recommendations_task` Celery 태스크

### Phase 3 (시뮬레이터 + API)
- [x] `GroupBookingSimulator` 구현 (`app/revenue/group_simulator.py` — 수락/거절/협상 권고)
- [x] Revenue API 엔드포인트 구현 (`app/api/routes/revenue.py`)
  - [x] `GET /revenue/dashboard` — RevPAR/ADR/점유율/채널믹스 대시보드 (RM-F40)
  - [x] `GET /revenue/recommendations` — AI 요율 권고 목록 (RM-F20)
  - [x] `POST /revenue/recommendations/{id}/decide` — 권고 수락/수정/거절 (RM-F21)
  - [x] `POST /revenue/simulate/group` — 단체 예약 시뮬레이션 (RM-F30)
  - [x] `GET /revenue/forecast` — 수요 예측 목록 조회 (RM-F10)
  - [x] `POST /revenue/events` / `GET /revenue/events` — 로컬 이벤트 관리 (RM-F02)

### Phase 4 (피드백 루프)
- [x] AI 권고 수락/거절 결과 추적 (`action_taken`, `decided_by`, `decided_at` 컬럼)
- [x] 실적 vs 예측 MAPE 계산 (`app/revenue/accuracy_tracker.py` — ForecastAccuracyTracker)
- [ ] 피드백 루프 지표 대시보드 (Admin UI — 미구현)
- [x] 테스트 커버리지: 63개 Revenue 테스트 전체 통과 + 전체 482개 통과
