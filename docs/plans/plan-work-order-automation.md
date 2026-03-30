# Plan: Work Order Automation 구현 계획

> **요구사항 참조**: [work_order_automation.md](../requirements/work_order_automation.md)
> **우선순위**: P1
> **관련 하위 문서**:
> - [plan-work-order-automation-2.md](./plan-work-order-automation-2.md) — 알림 시스템 / 모바일 상세

---

## 1. 현재 상태

Work Order 관련 코드 없음. 완전 신규 구현.

---

## 2. 전체 아키텍처

```
신고자 (하우스키핑/프런트)
    │ Work Order 생성 (웹/모바일)
    ▼
┌───────────────────────────────────────────────────────────┐
│                  Work Order API Server                      │
│                                                             │
│  POST /work-orders                                          │
│      │                                                      │
│      ▼                                                      │
│  ┌─────────────────────────────────┐                       │
│  │  AI 분류 엔진 (GPT-4o-mini)     │                       │
│  │  - 고장 유형 분류               │                       │
│  │  - 긴급도 판단 (Critical~Low)   │                       │
│  │  - 관련 PMS 객실 상태 확인      │                       │
│  └───────────────┬─────────────────┘                       │
│                  │                                          │
│  ┌───────────────▼─────────────────┐                       │
│  │  자동 배정 엔진                  │                       │
│  │  - 부서/유형별 담당자 매핑      │                       │
│  │  - 가용성 확인                  │                       │
│  │  - SLA 타이머 시작              │                       │
│  └───────────────┬─────────────────┘                       │
│                  │                                          │
│  ┌───────────────▼─────────────────┐                       │
│  │  알림 발송 (Push/Email)          │                       │
│  └─────────────────────────────────┘                       │
└───────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
┌─────────────────┐  ┌──────────────────┐
│  MySQL DB        │  │  SLA 모니터링    │
│  - work_orders  │  │  (Celery Beat)   │
│  - wo_history   │  │  - 에스컬레이션  │
│  - assignees    │  │  - 마감 알림     │
└─────────────────┘  └──────────────────┘
```

---

## 3. 구현 단계

### Phase 1 — 핵심 Work Order 생성 및 저장 (P0)

#### 3-1. DB 스키마

```sql
-- 담당자 역량 매핑 (어떤 유형을 처리할 수 있는지)
CREATE TABLE assignee_capabilities (
    user_id     INT        NOT NULL REFERENCES users(id),
    category    VARCHAR(50) NOT NULL,    -- '전기', '배관', '에어컨' 등
    priority    INT        NOT NULL DEFAULT 1,  -- 낮을수록 우선 배정
    is_available BOOLEAN   NOT NULL DEFAULT TRUE,
    PRIMARY KEY (user_id, category)
);

-- Work Order 메인 테이블
CREATE TABLE work_orders (
    id              VARCHAR(36)  PRIMARY KEY,          -- UUID
    wo_number       VARCHAR(20)  NOT NULL UNIQUE,       -- WO-2026-03001
    room_no         VARCHAR(20),
    location        VARCHAR(100),                       -- 로비, 식당 A 등
    category        VARCHAR(50)  NOT NULL,              -- AI 분류 결과
    description     TEXT         NOT NULL,
    photo_urls      JSON,                               -- 사진 목록
    severity        ENUM('critical','high','medium','low') NOT NULL,
    status          ENUM('open','assigned','in_progress','on_hold','completed','cancelled')
                    NOT NULL DEFAULT 'open',
    ai_classification JSON,                             -- AI 분류 전체 결과
    reported_by     INT          NOT NULL REFERENCES users(id),
    reported_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_to     INT          REFERENCES users(id),
    assigned_at     DATETIME,
    accepted_at     DATETIME,                           -- 배정 수락 시각
    started_at      DATETIME,
    completed_at    DATETIME,
    on_hold_reason  TEXT,
    resolution_note TEXT,
    parts_used      JSON,                               -- [{"name": "형광등", "qty": 2}]
    labor_hours     DECIMAL(4,1),
    external_vendor VARCHAR(200),
    external_contact VARCHAR(100),
    sla_deadline    DATETIME,                           -- 완료 목표 시각
    escalated       BOOLEAN      NOT NULL DEFAULT FALSE,
    escalated_at    DATETIME,
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_severity (severity),
    INDEX idx_reported_at (reported_at),
    INDEX idx_assigned_to (assigned_to)
);

-- Work Order 이력 (모든 상태 변경 기록)
CREATE TABLE work_order_history (
    id          INT      PRIMARY KEY AUTO_INCREMENT,
    wo_id       VARCHAR(36) NOT NULL REFERENCES work_orders(id),
    status      VARCHAR(20) NOT NULL,
    changed_by  INT         REFERENCES users(id),       -- NULL이면 시스템
    changed_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note        TEXT,
    INDEX idx_wo_id (wo_id)
);

-- SLA 설정 테이블
CREATE TABLE sla_settings (
    severity        ENUM('critical','high','medium','low') PRIMARY KEY,
    assign_limit_min INT NOT NULL,      -- 배정 목표 시간(분)
    complete_limit_min INT NOT NULL,    -- 완료 목표 시간(분)
    escalate_at_min INT NOT NULL        -- 에스컬레이션 기준 시간(분)
);

INSERT INTO sla_settings VALUES
('critical', 5,  120, 10),
('high',    15,  240, 30),
('medium',  60,  480, 120),
('low',     240, 4320, 480);
```

---

### Phase 2 — AI 분류 엔진

```python
# app/work_order/classifier.py

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
import json

CLASSIFICATION_PROMPT = """
호텔 시설 관리 전문가로서 다음 결함 신고를 분류하세요.

[신고 내용]
객실/위치: {location}
설명: {description}

[분류 규칙]

category (택1):
- 전기: 조명, 콘센트, TV, 전화기, 전기 차단기
- 배관: 수도꼭지, 변기, 샤워기, 배수, 누수
- 에어컨: 냉난방, 환기, 온도 조절
- 가구/비품: 침대, 소파, 책상, 금고, 커튼, 도어록
- 청결: 청소 불량, 린넨, 욕실 위생
- 안전: 화재 감지기, 비상구, 스프링클러
- 엘리베이터: 엘리베이터 고장/이상
- 기타: 위 분류에 해당 없는 것

severity (택1):
- critical: 안전 위험(감전, 화재, 수해 위험), 엘리베이터 갇힘, 투숙 완전 불가
- high: 오늘 체크인 예정 VIP 객실, 당일 재판매 예정 객실, 에어컨 완전 불가(여름)
- medium: 현재 투숙 중 불편(TV 안 됨, 콘센트 1개 불량 등)
- low: 빈 객실 경미한 결함, 예방 정비 요청

반드시 JSON만 반환:
{{
  "category": "전기",
  "severity": "high",
  "severity_reason": "VIP 체크인 예정 객실 (10시간 이내)",
  "recommended_action": "전기 배선 점검 및 형광등 교체",
  "estimated_duration_min": 30,
  "needs_external_vendor": false,
  "safety_risk": false,
  "confidence": 0.92
}}
"""

class WorkOrderClassifier:
    """WO-F14: 로컬 LLM 우선 분류, confidence < 0.80 시 클라우드 폴백"""

    CONFIDENCE_THRESHOLD = 0.80  # WO-F14: 분류 신뢰도 기준

    def __init__(self):
        from app.core.llm_router import llm_router, TaskTier
        self._router = llm_router
        self._tier = TaskTier.LOCAL_FIRST
        self.llm = self._router.get_llm(self._tier)          # 로컬 LLM
        self.fallback_llm = self._router.get_fallback(self._tier)  # 클라우드 폴백

    def classify(self, location: str, description: str, context: dict = None) -> dict:
        """
        WO-F14: 1차 로컬 LLM 분류 → confidence < 0.80이면 클라우드로 재분류
        context: PMS에서 조회한 객실 정보
        - vip_checkin_today: bool
        - checkout_today: bool
        - currently_occupied: bool
        """
        enhanced_description = description
        if context:
            if context.get("vip_checkin_today"):
                enhanced_description += " [참고: 오늘 VIP 체크인 예정 객실]"
            if context.get("checkout_today") and not context.get("currently_occupied"):
                enhanced_description += " [참고: 오늘 체크아웃 완료, 당일 재판매 예정]"

        prompt = CLASSIFICATION_PROMPT.format(
            location=location or "미지정",
            description=enhanced_description
        )

        # 1차: 로컬 LLM 분류
        result = self._invoke_llm(self.llm, prompt)
        result["_source"] = "local"

        # WO-F14: 신뢰도 미달 시 클라우드 폴백
        if result.get("confidence", 0.0) < self.CONFIDENCE_THRESHOLD and self.fallback_llm:
            cloud_result = self._invoke_llm(self.fallback_llm, prompt)
            if cloud_result.get("confidence", 0.0) > result.get("confidence", 0.0):
                cloud_result["_source"] = "cloud_fallback"
                return cloud_result

        return result

    def _invoke_llm(self, llm, prompt: str) -> dict:
        response = llm.invoke([HumanMessage(content=prompt)])
        try:
            return json.loads(response.content)
        except json.JSONDecodeError:
            return {
                "category": "기타",
                "severity": "medium",
                "severity_reason": "자동 분류 실패 - 수동 검토 필요",
                "confidence": 0.0,
            }
```

---

### Phase 3 — 자동 배정 엔진

```python
# app/work_order/assigner.py

from datetime import datetime, timedelta
from app.database.crud import get_available_assignees, update_work_order
from app.notifications.service import NotificationService

class AutoAssigner:
    def __init__(self):
        self.notifier = NotificationService()

    def assign(self, work_order: dict) -> dict | None:
        """
        1. 고장 유형에 매핑된 담당자 조회
        2. 현재 가용한(is_available=True) 담당자 필터
        3. priority 순으로 정렬, 첫 번째에게 배정
        4. 배정 알림 발송 + SLA 타이머 시작
        """
        category = work_order["ai_classification"]["category"]
        severity = work_order["severity"]

        # 담당 가능한 사용자 조회 (priority 오름차순)
        candidates = get_available_assignees(category=category)

        if not candidates:
            # 담당자 없음 → 관리자에게 에스컬레이션
            self._escalate_no_assignee(work_order)
            return None

        assignee = candidates[0]
        sla = self._get_sla(severity)

        # Work Order 업데이트
        update_work_order(work_order["id"], {
            "assigned_to": assignee["id"],
            "assigned_at": datetime.utcnow().isoformat(),
            "status": "assigned",
            "sla_deadline": (datetime.utcnow() + timedelta(minutes=sla["complete_limit_min"])).isoformat()
        })

        # 담당자 알림 발송
        self.notifier.send_push(
            user_id=assignee["id"],
            title=f"[{severity.upper()}] Work Order 배정 - {work_order['wo_number']}",
            message=f"객실 {work_order.get('room_no', '미지정')}: {work_order['description'][:50]}...",
            action_url=f"/work-orders/{work_order['id']}",
            priority="high" if severity in ("critical", "high") else "normal"
        )

        # SLA 수락 타이머 시작 (Celery)
        schedule_escalation_check.apply_async(
            args=[work_order["id"]],
            countdown=sla["escalate_at_min"] * 60
        )

        return assignee

    def _get_sla(self, severity: str) -> dict:
        sla_map = {
            "critical": {"assign_limit_min": 5,   "complete_limit_min": 120,  "escalate_at_min": 5},   # WO-F22
            "high":     {"assign_limit_min": 15,  "complete_limit_min": 240,  "escalate_at_min": 15},  # WO-F22
            "medium":   {"assign_limit_min": 60,  "complete_limit_min": 480,  "escalate_at_min": 120},
            "low":      {"assign_limit_min": 240, "complete_limit_min": 4320, "escalate_at_min": 480},
        }
        return sla_map[severity]
```

---

### Phase 4 — SLA 에스컬레이션 (Celery)

```python
# app/tasks/work_order_tasks.py

from celery import Celery
from app.database.crud import get_work_order, get_managers

celery_app = Celery("hotel_rag", broker="redis://localhost:6379/0")

@celery_app.task
def schedule_escalation_check(wo_id: str):
    """SLA 만료 시점에 실행되는 에스컬레이션 체크"""
    wo = get_work_order(wo_id)

    if wo["status"] in ("completed", "cancelled"):
        return  # 이미 처리 완료

    # 배정 수락이 안 된 경우
    if wo["status"] == "assigned" and not wo["accepted_at"]:
        escalate(wo, reason="배정 수락 미확인")
        return

    # 완료 기한 초과
    if wo["sla_deadline"] and datetime.utcnow() > datetime.fromisoformat(wo["sla_deadline"]):
        escalate(wo, reason="완료 기한 초과")

def escalate(wo: dict, reason: str):
    """에스컬레이션: 관리자에게 알림 + WO 플래그 설정"""
    update_work_order(wo["id"], {"escalated": True, "escalated_at": datetime.utcnow().isoformat()})

    managers = get_managers(department="engineering")
    for manager in managers:
        NotificationService().send_email(
            to=manager["email"],
            subject=f"[긴급] Work Order 에스컬레이션 - {wo['wo_number']}",
            body=f"""
Work Order {wo['wo_number']}이 SLA를 초과했습니다.

사유: {reason}
긴급도: {wo['severity'].upper()}
객실: {wo.get('room_no', '미지정')}
내용: {wo['description']}

즉시 확인이 필요합니다.
링크: https://hotel-app/work-orders/{wo['id']}
            """
        )
```

---

### Phase 5 — Work Order API 엔드포인트

```
# Work Order CRUD
POST   /api/v1/work-orders              # 신고 접수 + AI 분류 + 자동 배정
GET    /api/v1/work-orders              # 목록 조회 (긴급도 정렬, 필터)
GET    /api/v1/work-orders/{id}         # 단건 상세 조회
PATCH  /api/v1/work-orders/{id}/accept  # 담당자 배정 수락
PATCH  /api/v1/work-orders/{id}/status  # 상태 변경 (진행중/완료/보류)
PATCH  /api/v1/work-orders/{id}/complete # 완료 처리 (처리 내용, 부품, 시간 기록)
POST   /api/v1/work-orders/{id}/photos  # 사진 추가

# 대시보드 / 리포트
GET    /api/v1/work-orders/stats        # 집계 (긴급도별, 유형별, 기간별)
GET    /api/v1/work-orders/kpi          # KPI (평균 처리 시간, 에스컬레이션률)
GET    /api/v1/work-orders/repeat-patterns # 반복 고장 패턴 분석

# 담당자 관리
GET    /api/v1/assignees                # 담당자 목록 + 가용성
PATCH  /api/v1/assignees/{id}/availability # 가용성 토글

# Guest 신고 (인증 불필요, QR 코드 용)
POST   /api/v1/guest/work-orders        # 투숙객 직접 신고
```

---

### Phase 6 — 반복 고장 패턴 감지 (WO-F12)

```python
# app/work_order/pattern_analyzer.py

from datetime import datetime, timedelta
from app.database.crud import get_work_orders_in_range

class PatternAnalyzer:
    def analyze_repeat_patterns(self, days: int = 30) -> list[dict]:
        """최근 N일간 반복 고장 패턴 분석"""
        since = datetime.utcnow() - timedelta(days=days)
        wos = get_work_orders_in_range(since=since)

        # (location, category) 기준으로 그루핑
        from collections import defaultdict
        groups = defaultdict(list)
        for wo in wos:
            key = (wo.get("room_no") or wo.get("location"), wo["category"])
            groups[key].append(wo)

        patterns = []
        for (location, category), items in groups.items():
            if len(items) >= 3:  # 동일 위치+유형 3회 이상
                patterns.append({
                    "location": location,
                    "category": category,
                    "count": len(items),
                    "last_occurrence": max(w["reported_at"] for w in items),
                    "recommendation": f"{location}의 {category} 시스템 근본 점검 권고",
                    "work_order_ids": [w["id"] for w in items]
                })

        return sorted(patterns, key=lambda x: x["count"], reverse=True)
```

---

## 4. 파일 구조

```
app/
├── work_order/              # 신규 모듈
│   ├── __init__.py
│   ├── classifier.py        # AI 분류 엔진
│   ├── assigner.py          # 자동 배정 엔진
│   ├── service.py           # 비즈니스 로직 통합
│   └── pattern_analyzer.py  # 반복 고장 패턴 분석
│
├── api/routes/
│   └── work_orders.py       # Work Order API 엔드포인트
│
└── tasks/
    └── work_order_tasks.py  # Celery 에스컬레이션 태스크
```

---

## 5. 의존성 추가

```
# requirements.txt
celery>=5.3.0        # 비동기 태스크 큐
redis>=5.0.0         # Celery 브로커 + 결과 백엔드
tenacity>=8.2.0      # 재시도 로직

# docker-compose.yml에 Redis 서비스 추가
```

---

## 6. 테스트 전략

| 테스트 | 내용 |
|--------|------|
| AI 분류 정확도 | 20종 신고 케이스 golden set으로 카테고리/긴급도 정확도 측정 |
| 자동 배정 | 담당자 배정 → 수락 거절 → 재배정 흐름 검증 |
| SLA 에스컬레이션 | Critical WO 10분 미수락 시 관리자 알림 수신 확인 |
| 반복 패턴 | 동일 위치 3회 신고 → 패턴 감지 확인 |
| 동시성 | 다수 Critical WO 동시 생성 시 모두 정상 배정 |

---

## 7. 구현 체크리스트

### Phase 1 (DB + 기본 CRUD)
- [x] `work_orders`, `work_order_history`, `sla_settings` 테이블 생성 (`app/database/models.py`)
- [x] `assignee_capabilities` 테이블 + 기초 데이터 입력 (`seed_assignee_capabilities` in `app/tasks/work_order_tasks.py`)
- [x] Work Order 기본 CRUD `app/database/crud.py` 추가

### Phase 2 (AI 분류)
- [x] `app/work_order/classifier.py` WorkOrderClassifier 구현 (로컬 LLM 우선, confidence < 0.80 시 클라우드 폴백)
- [x] 분류 결과 DB 저장 (ai_classification JSON 컬럼)
- [x] 분류 테스트 작성 (`tests/test_work_order_classifier.py`)

### Phase 3 (자동 배정)
- [x] `app/work_order/assigner.py` AutoAssigner 구현 (AssigneeCapability 기반 배정, SLA 설정, 외부 업체 배정)
- [x] Celery + Redis 설정 (`docker-compose.yml`)
- [x] `schedule_escalation_check` Celery 태스크 구현 (`app/tasks/work_order_tasks.py`, WO-F22 SLA 에스컬레이션)
- [x] `check_all_sla` Celery Beat 태스크 구현 (30분마다 전체 미완료 WO 체크)

### Phase 4 (API)
- [x] `app/api/routes/work_orders.py` 전체 엔드포인트 구현
  - [x] `POST /work-orders` — 결함 신고 접수 + AI 분류 + 자동 배정 (WO-F01)
  - [x] `GET /work-orders` — 목록 조회 (필터 + 정렬)
  - [x] `GET /work-orders/{id}` — 단건 조회
  - [x] `PATCH /work-orders/{id}/status` — 상태 변경 (WO-F30)
  - [x] `PATCH /work-orders/{id}/complete` — 완료 처리 (WO-F31)
  - [x] `PATCH /work-orders/{id}/category` — 카테고리 수동 수정 (WO-F13)
  - [x] `PATCH /work-orders/{id}/vendor` — 외부 업체 배정 (WO-F23)
  - [x] `POST /work-orders/{id}/photos` — 사진 URL 추가
  - [x] `GET /work-orders/stats` — 통계 집계 (WO-F41)
  - [x] `GET /work-orders/kpi` — 주간 KPI 리포트 (WO-F42)

### Phase 5 (패턴 + KPI)
- [x] `PatternAnalyzer` 구현 (`app/work_order/pattern_analyzer.py`, 반복 고장 패턴 감지 WO-F12)
- [x] KPI 집계 쿼리 구현 (`WorkOrderService.get_weekly_kpi()`)
- [x] 테스트 커버리지: 102개 테스트 전체 통과 (`tests/test_work_order_*.py`)
