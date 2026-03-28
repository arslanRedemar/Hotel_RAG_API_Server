# Plan: Compliance & Audit Automation 구현 계획

> **요구사항 참조**: [compliance_audit.md](../requirements/compliance_audit.md)
> **우선순위**: P1
> **관련 하위 문서**:
> - [plan-compliance-audit-2.md](./plan-compliance-audit-2.md) — 보고서 생성 / 이상 감지 상세

---

## 1. 현재 상태

Compliance 관련 코드 없음. 완전 신규 구현.

---

## 2. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                 Compliance & Audit 시스템                    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  체크리스트 템플릿 관리 (Admin)                       │   │
│  │  - 점검 유형별 템플릿 작성                            │   │
│  │  - 법정 주기 설정 (일간/주간/월간/분기/연간)          │   │
│  └───────────────────────┬─────────────────────────────┘   │
│                           │                                  │
│  ┌──────────────────────▼──────────────────────────────┐   │
│  │  자동 스케줄 생성 엔진 (Celery Beat)                 │   │
│  │  - 주기에 따라 점검 일정 자동 생성                   │   │
│  │  - D-7, D-1 사전 알림                               │   │
│  │  - 미완료 시 경고 알림                               │   │
│  └───────────────────────┬─────────────────────────────┘   │
│                           │                                  │
│  ┌──────────────────────▼──────────────────────────────┐   │
│  │  모바일 점검 앱 (담당자)                              │   │
│  │  - 디지털 체크리스트 기록                            │   │
│  │  - NG 사진 첨부                                     │   │
│  │  - 전자서명 + 타임스탬프                             │   │
│  │  - 오프라인 지원                                     │   │
│  └───────────────────────┬─────────────────────────────┘   │
│                           │                                  │
│  ┌──────────────────────▼──────────────────────────────┐   │
│  │  이상 감지 엔진 (AI)                                 │   │
│  │  - 반복 NG 패턴 감지                                │   │
│  │  - 구역별 집중 이상 감지                             │   │
│  │  - Work Order 자동 연동                             │   │
│  └───────────────────────┬─────────────────────────────┘   │
│                           │                                  │
│  ┌──────────────────────▼──────────────────────────────┐   │
│  │  감사 보고서 자동 생성                               │   │
│  │  - 기간/유형/담당자별 필터                           │   │
│  │  - PDF 출력                                         │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. DB 스키마

```sql
-- 점검 템플릿
CREATE TABLE inspection_templates (
    id              VARCHAR(36)  PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    type            VARCHAR(50)  NOT NULL,   -- '위생', '소방', '안전', '객실품질'
    department_id   VARCHAR(50)  REFERENCES departments(id),
    frequency       ENUM('daily','weekly','monthly','quarterly','annually','adhoc') NOT NULL,
    frequency_day   INT,         -- 월간이면 몇 일, 주간이면 무슨 요일(0=월)
    items           JSON NOT NULL,           -- 체크리스트 항목 배열
    legal_reference VARCHAR(500),            -- 관련 법규 조항
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      INT REFERENCES users(id),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_type (type),
    INDEX idx_department (department_id)
);

-- 점검 스케줄 (자동 생성)
CREATE TABLE inspection_schedules (
    id              INT          PRIMARY KEY AUTO_INCREMENT,
    template_id     VARCHAR(36)  NOT NULL REFERENCES inspection_templates(id),
    scheduled_date  DATE         NOT NULL,
    assigned_to     INT          REFERENCES users(id),
    status          ENUM('scheduled','in_progress','completed','overdue') NOT NULL DEFAULT 'scheduled',
    notified_7d     BOOLEAN NOT NULL DEFAULT FALSE,   -- D-7 알림 발송 여부
    notified_1d     BOOLEAN NOT NULL DEFAULT FALSE,   -- D-1 알림 발송 여부
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_scheduled_date (scheduled_date),
    INDEX idx_status (status),
    INDEX idx_template_date (template_id, scheduled_date)
);

-- 점검 기록 (불변 - 제출 후 수정 불가)
CREATE TABLE inspection_records (
    id              VARCHAR(36)  PRIMARY KEY,          -- UUID
    schedule_id     INT          REFERENCES inspection_schedules(id),
    template_id     VARCHAR(36)  NOT NULL REFERENCES inspection_templates(id),
    location        VARCHAR(200) NOT NULL,
    inspector_id    INT          NOT NULL REFERENCES users(id),
    inspector_name  VARCHAR(100) NOT NULL,             -- 서명 시점 스냅샷
    inspected_at    DATETIME     NOT NULL,
    submitted_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    overall_result  ENUM('pass','conditional_pass','fail') NOT NULL,
    items           JSON NOT NULL,    -- 제출 시점의 전체 체크리스트 결과 스냅샷 (불변)
    ng_count        INT NOT NULL DEFAULT 0,
    corrective_actions JSON,          -- 조치 내역 (나중에 추가 가능)
    signature       VARCHAR(500) NOT NULL,             -- "이름 | ISO 타임스탬프"
    source          ENUM('mobile','web') NOT NULL DEFAULT 'mobile',
    INDEX idx_template (template_id),
    INDEX idx_inspector (inspector_id),
    INDEX idx_inspected_at (inspected_at),
    INDEX idx_overall_result (overall_result)
);

-- 조치 이력 (NG 항목에 대한 후속 조치)
CREATE TABLE inspection_corrective_actions (
    id              INT       PRIMARY KEY AUTO_INCREMENT,
    record_id       VARCHAR(36) NOT NULL REFERENCES inspection_records(id),
    item_id         VARCHAR(100) NOT NULL,    -- 체크리스트 항목 ID
    action          TEXT NOT NULL,
    work_order_id   VARCHAR(36) REFERENCES work_orders(id),   -- 연동된 WO
    completed_by    INT REFERENCES users(id),
    completed_at    DATETIME,
    verification_photo_url VARCHAR(500),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_record_id (record_id)
);

-- 법규 변경 이력
CREATE TABLE compliance_regulations (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    code        VARCHAR(100) NOT NULL UNIQUE,   -- 'FOOD_SAFETY_ACT_ART15'
    name        VARCHAR(300) NOT NULL,
    content     TEXT,
    effective_date DATE NOT NULL,
    related_template_ids JSON,                  -- 영향받는 템플릿 목록
    applied     BOOLEAN NOT NULL DEFAULT FALSE, -- 체크리스트에 반영됐는지
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. 점검 템플릿 항목 데이터 구조

```json
{
  "id": "tpl-hygiene-kitchen",
  "name": "주방 위생 점검표",
  "type": "위생",
  "department_id": "fb",
  "frequency": "daily",
  "items": [
    {
      "id": "h-001",
      "category": "온도 관리",
      "description": "냉장고 온도 4°C 이하 유지",
      "required": true,
      "photo_required_on_ng": true,
      "legal_ref": "식품위생법 제3조",
      "sop_link": "/sops/sop-kitchen-temp-001"
    },
    {
      "id": "h-002",
      "category": "식재료 관리",
      "description": "모든 식재료 유통기한 확인 및 선입선출 준수",
      "required": true,
      "photo_required_on_ng": true,
      "legal_ref": "식품위생법 제7조"
    },
    {
      "id": "h-003",
      "category": "개인위생",
      "description": "조리 직원 위생모/앞치마 착용 여부",
      "required": true,
      "photo_required_on_ng": false
    }
  ],
  "legal_reference": "식품위생법, 공중위생관리법"
}
```

---

## 5. 구현 단계

### Phase 1 — 템플릿 + 스케줄 관리 (CA-F01~F13)

#### 5-1. 자동 스케줄 생성 (Celery Beat)

```python
# app/tasks/inspection_tasks.py

from celery import Celery
from celery.schedules import crontab
from datetime import date, timedelta

celery_app = Celery("hotel_rag", broker="redis://localhost:6379/0")

# 매일 자정에 다음 날 스케줄 생성 및 알림 처리
celery_app.conf.beat_schedule = {
    'generate-daily-schedules': {
        'task': 'app.tasks.inspection_tasks.generate_schedules',
        'schedule': crontab(hour=0, minute=5),  # 매일 00:05
    },
    'send-inspection-reminders': {
        'task': 'app.tasks.inspection_tasks.send_reminders',
        'schedule': crontab(hour=8, minute=0),  # 매일 08:00
    },
    'check-overdue-inspections': {
        'task': 'app.tasks.inspection_tasks.check_overdue',
        'schedule': crontab(hour='*/2'),         # 2시간마다
    },
}

@celery_app.task
def generate_schedules():
    """활성 템플릿의 주기에 따라 미래 스케줄 자동 생성"""
    today = date.today()
    templates = get_active_templates()

    for template in templates:
        dates_to_schedule = calculate_schedule_dates(template, today, days_ahead=30)

        for scheduled_date in dates_to_schedule:
            # 이미 존재하면 건너뜀
            if not schedule_exists(template["id"], scheduled_date):
                create_schedule({
                    "template_id": template["id"],
                    "scheduled_date": scheduled_date,
                    "assigned_to": get_default_assignee(template["department_id"])
                })

def calculate_schedule_dates(template: dict, from_date: date, days_ahead: int) -> list[date]:
    """템플릿 주기에 따라 앞으로 N일간 점검 날짜 계산"""
    dates = []
    frequency = template["frequency"]

    for day_offset in range(days_ahead):
        target_date = from_date + timedelta(days=day_offset)

        if frequency == "daily":
            dates.append(target_date)
        elif frequency == "weekly":
            if target_date.weekday() == template.get("frequency_day", 0):  # 기본: 월요일
                dates.append(target_date)
        elif frequency == "monthly":
            if target_date.day == template.get("frequency_day", 1):
                dates.append(target_date)
        elif frequency == "quarterly":
            if target_date.month % 3 == 0 and target_date.day == template.get("frequency_day", 1):
                dates.append(target_date)
        elif frequency == "annually":
            if target_date.month == 1 and target_date.day == 1:
                dates.append(target_date)

    return dates

@celery_app.task
def send_reminders():
    """D-7, D-1 알림 발송"""
    today = date.today()

    for days_ahead, flag_field in [(7, "notified_7d"), (1, "notified_1d")]:
        target_date = today + timedelta(days=days_ahead)
        pending = get_scheduled_inspections(
            scheduled_date=target_date,
            status="scheduled",
            notified=False,
            flag_field=flag_field
        )

        for schedule in pending:
            template = get_template(schedule["template_id"])
            assignee = get_user(schedule["assigned_to"])

            NotificationService().send_email(
                to=assignee["email"],
                subject=f"[점검 예정] {template['name']} - {target_date} (D-{days_ahead})",
                html_body=render_reminder_email(template, schedule, target_date)
            )

            # 알림 발송 완료 플래그 업데이트
            update_schedule(schedule["id"], {flag_field: True})

@celery_app.task
def check_overdue():
    """미완료 점검 감지 및 경고 알림"""
    yesterday = date.today() - timedelta(days=1)
    overdue = get_scheduled_inspections(scheduled_date=yesterday, status="scheduled")

    for schedule in overdue:
        update_schedule(schedule["id"], {"status": "overdue"})

        template = get_template(schedule["template_id"])
        managers = get_managers(department=template["department_id"])

        for manager in managers:
            NotificationService().send_email(
                to=manager["email"],
                subject=f"[점검 미완료] {template['name']} - {yesterday}",
                html_body=f"<p>어제 예정된 {template['name']} 점검이 완료되지 않았습니다.</p>"
            )
```

---

### Phase 2 — 모바일 점검 기록 (CA-F01~F05)

#### 5-2. 점검 기록 제출 API

```python
# app/api/routes/inspections.py

@router.post("/inspection-records", response_model=InspectionRecordOut)
async def submit_inspection_record(
    record: InspectionRecordCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. NG 항목에 사진 필수 검증
    for item in record.items:
        item_def = get_template_item(record.template_id, item.item_id)
        if (item.result == "NG"
            and item_def.get("photo_required_on_ng")
            and not item.photo_url):
            raise HTTPException(
                status_code=422,
                detail=f"항목 '{item_def['description']}'에 NG 사진 첨부가 필요합니다"
            )
        if item.result == "NG" and not item.note:
            raise HTTPException(
                status_code=422,
                detail=f"항목 '{item_def['description']}'에 NG 비고 입력이 필요합니다"
            )

    # 2. 점검 기록 저장 (불변)
    ng_count = sum(1 for item in record.items if item.result == "NG")
    overall = "fail" if ng_count >= 3 else ("conditional_pass" if ng_count > 0 else "pass")

    record_id = str(uuid.uuid4())
    inspection_record = {
        "id": record_id,
        "template_id": record.template_id,
        "schedule_id": record.schedule_id,
        "location": record.location,
        "inspector_id": current_user.id,
        "inspector_name": current_user.full_name,
        "inspected_at": record.inspected_at,
        "submitted_at": datetime.utcnow(),
        "overall_result": overall,
        "items": [item.dict() for item in record.items],
        "ng_count": ng_count,
        "signature": f"{current_user.full_name} | {datetime.utcnow().isoformat()}",
    }
    save_inspection_record(db, inspection_record)

    # 3. 스케줄 상태 완료로 업데이트
    if record.schedule_id:
        update_schedule(record.schedule_id, {"status": "completed"})

    # 4. NG 항목에 대해 Work Order 자동 생성 연동
    if ng_count > 0:
        auto_create_work_orders_from_ng(record_id, record.items, record.location, current_user.id)

    # 5. 이상 패턴 감지 트리거
    analyze_anomaly_patterns.delay(record.template_id, record.location)

    return record_id
```

#### 5-3. NG 항목 → Work Order 자동 연동

```python
# app/inspections/service.py

def auto_create_work_orders_from_ng(
    record_id: str,
    items: list,
    location: str,
    reporter_id: int
):
    """NG 항목 중 시설 관련 항목은 자동으로 Work Order 생성"""
    facility_categories = {"소방", "안전", "전기", "배관"}  # 시설 관련 NG

    for item in items:
        if item["result"] != "NG":
            continue

        template_item = get_template_item_by_id(item["item_id"])
        if not template_item:
            continue

        # 시설 관련 항목 → Work Order 자동 생성
        item_category = template_item.get("maintenance_category")
        if item_category in facility_categories:
            from app.work_order.service import WorkOrderService
            wo = WorkOrderService().create({
                "location": location,
                "category": item_category,
                "description": f"[점검 NG 자동] {template_item['description']}: {item.get('note', '')}",
                "photo_urls": [item["photo_url"]] if item.get("photo_url") else [],
                "reported_by": reporter_id,
                "source": f"inspection_record:{record_id}"
            })

            # 조치 이력에 WO 연동 기록
            save_corrective_action({
                "record_id": record_id,
                "item_id": item["item_id"],
                "action": "Work Order 자동 생성",
                "work_order_id": wo["id"]
            })
```

---

### Phase 3 — 이상 감지 + 감사 보고서

> 상세: [plan-compliance-audit-2.md](./plan-compliance-audit-2.md)

---

## 6. 점검 API 엔드포인트

```
# 템플릿 관리
GET    /api/v1/inspection-templates
POST   /api/v1/inspection-templates          (Admin)
GET    /api/v1/inspection-templates/{id}
PUT    /api/v1/inspection-templates/{id}      (Admin)
DELETE /api/v1/inspection-templates/{id}      (Admin)

# 스케줄 조회
GET    /api/v1/inspection-schedules           # 캘린더 뷰용
GET    /api/v1/inspection-schedules/today     # 오늘 점검 목록

# 점검 기록 (불변)
POST   /api/v1/inspection-records            # 점검 기록 제출
GET    /api/v1/inspection-records            # 이력 조회 (기간/유형/담당자 필터)
GET    /api/v1/inspection-records/{id}       # 단건 조회

# 조치 이력 (수정 가능)
POST   /api/v1/inspection-records/{id}/corrective-actions
GET    /api/v1/inspection-records/{id}/corrective-actions

# 감사 보고서
POST   /api/v1/inspection-reports/generate  # 보고서 생성 (PDF 다운로드)
GET    /api/v1/inspection-reports/stats     # 통계 집계

# 이상 감지
GET    /api/v1/inspections/anomalies        # 감지된 이상 패턴 목록

# 법규 관리
GET    /api/v1/compliance-regulations
POST   /api/v1/compliance-regulations       (Admin)
```

---

## 7. 파일 구조

```
app/
├── inspections/              # 신규 모듈
│   ├── __init__.py
│   ├── service.py            # 점검 기록 비즈니스 로직
│   ├── anomaly_detector.py   # 이상 패턴 감지
│   └── report_generator.py   # PDF 보고서 생성
│
├── api/routes/
│   └── inspections.py        # 점검 API 엔드포인트
│
└── tasks/
    └── inspection_tasks.py   # 스케줄 생성, 알림, 미완료 감지
```

---

## 8. 구현 체크리스트

### Phase 1 (스케줄 + 템플릿)
- [ ] `inspection_templates`, `inspection_schedules` 테이블 생성
- [ ] 기본 템플릿 데이터 (위생/소방/안전/객실품질) 삽입
- [ ] `generate_schedules` Celery Beat 태스크 구현
- [ ] `send_reminders`, `check_overdue` 태스크 구현
- [ ] 템플릿/스케줄 CRUD API 구현

### Phase 2 (모바일 점검)
- [ ] `inspection_records`, `inspection_corrective_actions` 테이블 생성
- [ ] `POST /inspection-records` 제출 API (NG 검증, 불변 저장)
- [ ] NG → Work Order 자동 생성 연동
- [ ] 모바일 점검 UI 구현 (Next.js)
- [ ] 오프라인 점검 기록 → 재연결 시 동기화

### Phase 3 (감지 + 보고서)
- [ ] `AnomalyDetector` 구현 (반복 NG, 구역 집중)
- [ ] PDF 보고서 생성 (`reportlab`)
- [ ] 감사 보고서 필터 UI
