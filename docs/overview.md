# Hotel AX (Automation for Excellence) — 전체 시스템 구조 개요

> 작성일: 2026-03-27
> 버전: 1.0.0

---

## 1. 시스템 개요

Hotel AX는 호텔 운영 전반의 지식 관리·자동화를 위한 **RAG 기반 AI 시스템**이다.
단순 챗봇이 아닌, 호텔 실무 프로세스(SOP, 작업 지시, 컴플라이언스, 수익 관리)에 AI를 깊게 통합하여 운영 효율을 극대화하는 **AX(Automation for Excellence)** 플랫폼이다.

```
[ 호텔 직원 / 관리자 / 외부 시스템 ]
           ↓
  [ Next.js 14 Frontend ]  ← Web Push / Email / SMS 알림
           ↓ REST API / WebSocket
  [ FastAPI Backend (Python 3.11) ]
    ├─ RAG Assistant       (LangGraph + ChromaDB)
    ├─ SOP Digitalization  (OCR + GPT 추출)
    ├─ Work Order Auto     (AI 분류 + 자동배정)
    ├─ Compliance & Audit  (점검 스케줄 + 보고서)
    └─ Revenue Management  (예측 + 요율 권고)
           ↓
  [ Celery + Redis ] ← 비동기 / 스케줄 작업
           ↓
  [ MySQL 8.0 ] + [ ChromaDB ] + [ S3 / MinIO ]
```

---

## 2. 5대 기능 모듈

### 2.1 RAG Assistant (P0 — 핵심)

| 항목 | 내용 |
|------|------|
| 목적 | 호텔 내부 문서(PDF/DOCX/TXT) 기반 자연어 Q&A |
| AI 스택 | OpenAI GPT-4o-mini + text-embedding-3-small + LangGraph |
| 벡터 DB | ChromaDB (로컬 퍼시스턴트) |
| 특징 | 부서별 필터링, 출처 인용, 할루시네이션 방지, 대화 히스토리 |
| 구현 단계 | Phase 1(DOCX+JWT) → 2(버전관리) → 3(부서필터) → 4(Next.js UI) |

**핵심 컴포넌트**:
```
RAGAssistant
  ├─ DocumentProcessor   (PDF/DOCX/TXT 파싱 → 청킹)
  ├─ VectorIndexer       (ChromaDB 임베딩 저장)
  ├─ LangGraph Pipeline  (retrieve → grade → generate → hallucination_check)
  └─ QueryRouter         (직접답변 vs RAG 라우팅)
```

---

### 2.2 SOP Digitalization (P1)

| 항목 | 내용 |
|------|------|
| 목적 | 종이/이미지 SOP → 구조화 디지털 문서 자동 변환 |
| OCR 엔진 | Tesseract 5.x (기본) / Google Vision API (고품질) |
| AI 추출 | GPT-4o-mini — 제목, 단계, 책임자, 안전 주의 추출 |
| 출력 | ChromaDB 인덱싱 + reportlab PDF 재생성 |
| 특징 | OpenCV 이미지 전처리, 신뢰도 점수, 검토 상태머신 |

**처리 파이프라인**:
```
[이미지/PDF 업로드]
    → OCRProcessor (전처리 → Tesseract/Vision)
    → SOPExtractor (GPT-4 구조 추출)
    → 신뢰도 평가 → 검토 큐 (낮으면 수동 검토)
    → 승인 → ChromaDB 인덱싱 + PDF 재생성
    → Acknowledge 서명 수집
```

**SOP 상태머신**:
```
DRAFT → PENDING_REVIEW → APPROVED → PUBLISHED
                ↑               ↓
           REJECTED ←──── 수정 요청
```

---

### 2.3 Work Order Automation (P1)

| 항목 | 내용 |
|------|------|
| 목적 | 고장 신고 → AI 분류 → 자동 배정 → SLA 추적 |
| 분류 | GPT-4o-mini (카테고리 + 긴급도 4단계) |
| 배정 | 스킬 매칭 + 가용성 + 워크로드 점수 기반 |
| SLA | Critical 2h / High 4h / Medium 24h / Low 72h |
| 오프라인 | PWA + IndexedDB (연결 없이 신고 가능) |

**긴급도 분류**:
```
Critical  → 즉시 알림 + 2시간 SLA + 에스컬레이션
High      → 즉시 배정 + 4시간 SLA
Medium    → 일반 큐   + 24시간 SLA
Low       → 예약 큐   + 72시간 SLA
```

**에스컬레이션 체인**:
```
SLA 50% 경과 → 담당자 알림
SLA 80% 경과 → 관리자 알림
SLA 초과     → 임원 알림 + 자동 재배정
```

---

### 2.4 Compliance & Audit Automation (P1)

| 항목 | 내용 |
|------|------|
| 목적 | 법정 점검 스케줄 자동 생성, 모바일 점검, 감사 보고서 |
| 스케줄 | Celery Beat — 법정 주기(일/주/월/분기/반기/연) |
| 점검 | 모바일 체크리스트 (사진 첨부, GPS 위치 기록) |
| 이상감지 | 반복 NG 패턴, 구역 집중 감지, 계절성 분석 |
| 보고서 | reportlab PDF (한글 NanumGothic 폰트) |

**NG 처리 흐름**:
```
점검 중 NG 발생
    → 사진 + 메모 첨부
    → 시정 조치 생성 (due_date 자동 설정)
    → Work Order 연동 (is_work_order=True)
    → 완료 확인 → 재점검 스케줄
```

**이상감지 규칙**:
```
반복 NG    : 30일 내 동일 항목 3회 이상 → 알림
구역 집중  : 동일 구역 5개 이상 NG → 구조적 문제 플래그
계절성     : 전년 동월 대비 NG 증가율 20% 이상
```

---

### 2.5 Revenue Management Support (P2)

| 항목 | 내용 |
|------|------|
| 목적 | AI 요율 권고, 수요 예측, 경쟁사 모니터링 |
| 데이터 | PMS API (직접 연동) + 수동 입력 fallback |
| 예측 | 이동평균(단기) → Prophet(중기) → XGBoost(장기) |
| 요율 권고 | GPT-4 컨텍스트 + 룰 기반 검증 (±30% 가드레일) |
| 시뮬레이터 | 단체 예약 수락/거절 시나리오 분석 |

**예측 모델 스택**:
```
7일 이내  → 이동평균 (단순, 빠름)
7~30일    → Facebook Prophet (계절성, 이벤트)
30일 이상 → XGBoost (다변량: 요일, 이벤트, 경쟁사 요율)
```

**요율 결정 흐름**:
```
수요 예측 → 경쟁사 요율 수집 → AI 권고 생성
    → 가드레일 검증 (±30%)
    → 수동 검토 (Manager 이상)
    → 승인 → PMS 적용
```

---

## 3. 공통 인프라

### 3.1 인증 & 권한

```
JWT (Access 30분 + Refresh 7일)
  ├─ Admin   — 전체 기능
  ├─ Manager — 부서 전체 + 요율 승인
  └─ Staff   — 소속 부서 읽기 + 작업 수행
```

**토큰 갱신 흐름**:
```
Access 만료 → /auth/refresh (Refresh Token)
             → 새 Access + Refresh 발급 (Rotation)
             → 구 Refresh Token 블랙리스트 등록
```

---

### 3.2 알림 시스템

| 채널 | 용도 |
|------|------|
| Email (SMTP) | 작업 배정, SLA 경고, 보고서 첨부 |
| Web Push (VAPID) | 모바일 실시간 알림 (PWA) |
| SMS (옵션) | Critical 긴급 공지 |
| WebSocket | 대시보드 실시간 업데이트 |

---

### 3.3 파일 저장소

```
FileStorageService
  ├─ 업로드   → S3 (또는 MinIO 로컬)
  ├─ 다운로드 → Presigned URL (1시간 TTL)
  ├─ 삭제     → Soft Delete (is_deleted=True)
  └─ 정리     → Celery Beat (7일 후 실제 삭제)
```

---

### 3.4 관찰성 (Observability)

```
JSONFormatter 구조화 로그
  └─ request_id, user_id, duration_ms, status_code
RequestLoggingMiddleware → 모든 API 요청 자동 기록
MetricsMiddleware        → 응답 시간 p50/p95/p99
CircuitBreaker           → 외부 API 장애 격리
  └─ CLOSED → OPEN (5회 실패) → HALF_OPEN (30초)
```

---

## 4. 데이터베이스 스키마 맵

### 4.1 테이블 목록

| 모듈 | 테이블명 | 설명 |
|------|----------|------|
| 공통 | departments | 부서 |
| 공통 | users | 사용자 (JWT 인증) |
| 공통 | files | 파일 메타데이터 |
| 공통 | audit_logs | 불변 감사 로그 |
| RAG | documents | 업로드 문서 |
| RAG | document_versions | 버전 이력 |
| RAG | sop_acknowledgements | 확인 서명 |
| SOP | sops | SOP 문서 |
| SOP | sop_version_history | SOP 버전 이력 |
| Work Order | work_orders | 작업 지시서 |
| Work Order | work_order_comments | 작업 코멘트 |
| Work Order | sla_settings | SLA 기준 설정 |
| Work Order | skill_tags | 기술 태그 |
| Compliance | inspection_templates | 점검 항목 템플릿 |
| Compliance | inspection_schedules | 점검 스케줄 |
| Compliance | inspection_records | 점검 실시 기록 |
| Compliance | corrective_actions | 시정 조치 |
| Compliance | compliance_regulations | 법정 규제 |
| Revenue | daily_metrics | 일별 KPI (ADR, OCC, RevPAR) |
| Revenue | competitor_rates | 경쟁사 요율 |
| Revenue | local_events | 지역 이벤트 |
| Revenue | rate_recommendations | AI 요율 권고 |
| Revenue | demand_forecasts | 수요 예측 결과 |
| Revenue | group_booking_simulations | 단체 예약 시뮬레이션 |

### 4.2 핵심 관계도

```
departments ──< users ──< work_orders
                    └──< sop_acknowledgements
                    └──< inspection_records

documents ──< document_versions
sops ──< sop_version_history

inspection_templates ──< inspection_schedules ──< inspection_records
inspection_records ──< corrective_actions ──> work_orders (연동)

daily_metrics ──> rate_recommendations
competitor_rates ──> rate_recommendations
demand_forecasts ──> rate_recommendations
```

---

## 5. API 엔드포인트 카탈로그

### 5.1 인증 (`/auth`)
```
POST /auth/login              # 로그인 → Access + Refresh Token
POST /auth/refresh            # 토큰 갱신
POST /auth/logout             # 로그아웃 (Refresh 블랙리스트)
GET  /auth/me                 # 현재 사용자 정보
```

### 5.2 RAG Assistant (`/rag`)
```
POST /rag/query               # 자연어 질의 → RAG 답변
POST /rag/documents/upload    # 문서 업로드 (PDF/DOCX/TXT)
GET  /rag/documents           # 문서 목록 (부서 필터)
DELETE /rag/documents/{id}    # 문서 삭제 (소프트)
GET  /rag/documents/{id}/versions  # 버전 이력
POST /rag/documents/{id}/acknowledge  # 확인 서명
```

### 5.3 SOP (`/sop`)
```
POST /sop/upload              # SOP 이미지/PDF 업로드
GET  /sop                     # SOP 목록
GET  /sop/{id}                # SOP 상세
PUT  /sop/{id}/status         # 상태 변경 (승인/거절)
GET  /sop/{id}/export         # PDF 내보내기
POST /sop/{id}/acknowledge    # 직원 확인 서명
```

### 5.4 Work Order (`/work-orders`)
```
POST /work-orders             # 신고 생성 (AI 분류 자동)
GET  /work-orders             # 목록 (상태/긴급도/담당자 필터)
GET  /work-orders/{id}        # 상세 + 타임라인
PUT  /work-orders/{id}/status # 상태 업데이트
POST /work-orders/{id}/assign # 수동 재배정
POST /work-orders/{id}/comments  # 코멘트 추가
GET  /work-orders/analytics   # 분석 대시보드
```

### 5.5 Compliance (`/compliance`)
```
GET  /compliance/schedules    # 점검 스케줄
POST /compliance/schedules    # 스케줄 수동 생성
POST /compliance/records      # 점검 실시 기록
PUT  /compliance/records/{id}/items/{item_id}  # 항목 결과 저장
GET  /compliance/reports/{id}/pdf  # 감사 보고서 PDF
GET  /compliance/anomalies    # 이상 감지 결과
```

### 5.6 Revenue (`/revenue`)
```
GET  /revenue/dashboard       # KPI 대시보드
POST /revenue/metrics/manual  # 수동 데이터 입력
POST /revenue/competitor-rates  # 경쟁사 요율 입력
GET  /revenue/recommendations  # AI 요율 권고 목록
POST /revenue/recommendations/{id}/approve  # 권고 승인
POST /revenue/forecast        # 수요 예측 실행
POST /revenue/group-simulation  # 단체 예약 시뮬레이션
```

---

## 6. 구현 로드맵

### Phase 0 — 기반 (현재 완료)
- [x] FastAPI 기본 서버
- [x] ChromaDB 연동
- [x] PDF/TXT 문서 인덱싱
- [x] 기본 RAG 쿼리

### Phase 1 — 핵심 기능 (4~6주)
- [ ] JWT 인증 시스템 (Access + Refresh + Blacklist)
- [ ] DOCX 문서 처리 (python-docx)
- [ ] Work Order AI 분류 + 자동배정
- [ ] SOP OCR 파이프라인 (Tesseract)
- [ ] 점검 스케줄 자동 생성 (Celery Beat)
- [ ] MySQL 스키마 전체 적용

### Phase 2 — 고도화 (6~10주)
- [ ] Next.js 14 프론트엔드
- [ ] PWA + 오프라인 지원 (IndexedDB + Service Worker)
- [ ] Web Push 알림 (VAPID)
- [ ] SOP 검토 워크플로우 (상태머신)
- [ ] 이상감지 엔진 (AnomalyDetector)
- [ ] reportlab PDF 보고서

### Phase 3 — 수익 관리 (10~14주)
- [ ] PMS API 연동
- [ ] Prophet + XGBoost 수요 예측
- [ ] AI 요율 권고 엔진
- [ ] 경쟁사 요율 수집
- [ ] 단체 예약 시뮬레이터

### Phase 4 — 안정화 (14~16주)
- [ ] Google Vision API (고품질 OCR)
- [ ] Circuit Breaker 전체 적용
- [ ] 구조화 로그 + 메트릭
- [ ] GitHub Actions CI/CD
- [ ] 부하 테스트 + 성능 최적화

---

## 7. 기술 스택 전체도

```
┌─────────────────────────────────────────────────────┐
│                   FRONTEND                           │
│  Next.js 14 (App Router) + TypeScript + Tailwind    │
│  React Query, Zustand, PWA, WebSocket               │
└──────────────────┬──────────────────────────────────┘
                   │ REST API + WebSocket
┌──────────────────▼──────────────────────────────────┐
│                   BACKEND                            │
│  FastAPI + Python 3.11                              │
│  SQLAlchemy 2.0 + Pydantic v2                       │
│  LangChain + LangGraph + OpenAI SDK                 │
│  Celery (Worker + Beat) + Redis                     │
│  reportlab, python-docx, Tesseract, OpenCV          │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│                DATA LAYER                            │
│  MySQL 8.0    — 관계형 데이터                        │
│  ChromaDB     — 벡터 임베딩                          │
│  Redis        — Celery 브로커 + 토큰 블랙리스트       │
│  S3 / MinIO   — 파일 저장소                          │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│                AI / ML                               │
│  OpenAI GPT-4o-mini — LLM (RAG, 분류, 추출, 권고)   │
│  text-embedding-3-small — 임베딩                    │
│  Facebook Prophet — 시계열 예측                      │
│  XGBoost — 다변량 예측                               │
│  Tesseract 5.x / Google Vision — OCR                │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│                INFRASTRUCTURE                        │
│  Docker + docker-compose                            │
│  GitHub Actions (CI: test → lint → build → deploy) │
│  Nginx (리버스 프록시)                               │
└─────────────────────────────────────────────────────┘
```

---

## 8. 파일 구조 맵

```
Hotel_RAG_API_Server/
├─ app/
│   ├─ main.py
│   ├─ core/
│   │   ├─ config.py          # 환경변수 설정
│   │   ├─ security.py        # JWT 유틸리티
│   │   ├─ logging.py         # JSONFormatter
│   │   ├─ middleware.py      # 요청 로깅 + 메트릭
│   │   └─ circuit_breaker.py
│   ├─ database/
│   │   ├─ base.py            # SQLAlchemy 설정
│   │   └─ models/            # ORM 모델 (모듈별)
│   ├─ api/
│   │   ├─ auth.py
│   │   ├─ rag.py
│   │   ├─ sop.py
│   │   ├─ work_orders.py
│   │   ├─ compliance.py
│   │   └─ revenue.py
│   ├─ services/
│   │   ├─ rag/
│   │   │   ├─ document_processor.py
│   │   │   ├─ vector_indexer.py
│   │   │   └─ rag_pipeline.py    # LangGraph
│   │   ├─ sop/
│   │   │   ├─ ocr_processor.py   # Tesseract/Vision
│   │   │   └─ sop_extractor.py   # GPT 구조 추출
│   │   ├─ work_order/
│   │   │   ├─ classifier.py      # GPT 분류
│   │   │   ├─ auto_assigner.py
│   │   │   └─ pattern_analyzer.py
│   │   ├─ compliance/
│   │   │   ├─ anomaly_detector.py
│   │   │   └─ report_generator.py # reportlab
│   │   ├─ revenue/
│   │   │   ├─ pms_collector.py
│   │   │   ├─ demand_forecaster.py # Prophet + XGBoost
│   │   │   └─ rate_engine.py      # AI 요율 권고
│   │   ├─ notification/
│   │   │   ├─ email_service.py
│   │   │   └─ push_service.py    # VAPID
│   │   └─ storage/
│   │       └─ file_storage.py    # S3 / MinIO
│   └─ workers/
│       ├─ celery_app.py
│       ├─ sla_tasks.py           # Work Order SLA
│       ├─ inspection_tasks.py    # 점검 스케줄
│       └─ revenue_tasks.py       # 데이터 수집
├─ docs/
│   ├─ requirements/              # 요구사항 (6개 파일)
│   ├─ plans/                     # 구현 계획 (12개 파일)
│   ├─ overview.md                # ← 이 문서
│   └─ architecture-visualization.html
├─ docker-compose.yml
├─ Dockerfile
└─ requirements.txt

hotel-rag/                        # Next.js 14 Frontend
├─ app/
│   ├─ (auth)/login/
│   ├─ dashboard/
│   ├─ rag/                       # RAG 채팅
│   ├─ sop/                       # SOP 관리
│   ├─ work-orders/               # 작업 지시서
│   ├─ compliance/                # 점검 체크리스트
│   └─ revenue/                   # 수익 대시보드
├─ components/
│   ├─ rag/    ChatWindow, SourcePanel
│   ├─ sop/    SOPCard, OCRUploader
│   ├─ work-order/  WorkOrderBoard, StatusBadge
│   ├─ compliance/  ChecklistForm, ScheduleCalendar
│   └─ revenue/    KPICards, RateChart, SimulatorForm
└─ public/
    └─ sw.js                      # Service Worker (PWA)
```

---

## 9. 모듈 간 의존성

```
system-common ←─── 모든 모듈 (인증, 로깅, 파일, 알림)
      │
      ├─ RAG Assistant  ←── SOP (SOP 승인 시 RAG 인덱싱)
      │
      ├─ SOP Digitalization
      │
      ├─ Work Order Automation ←── Compliance (NG → Work Order)
      │
      ├─ Compliance & Audit ──→ Work Order
      │
      └─ Revenue Management (독립적, PMS API 의존)
```

---

## 10. 보안 체크리스트

- [x] JWT Refresh Token Rotation + 블랙리스트
- [x] bcrypt 패스워드 해시 (cost factor 12)
- [x] Role-Based Access Control (Admin/Manager/Staff)
- [x] Presigned URL (직접 S3 접근 방지)
- [x] 불변 감사 로그 (audit_logs — 수정/삭제 불가)
- [x] SQL Injection 방지 (SQLAlchemy ORM + 파라미터 바인딩)
- [x] 파일 업로드 검증 (MIME 타입 + 확장자 + 크기)
- [ ] Rate Limiting (로그인 시도 제한)
- [ ] HTTPS 전용 (프로덕션)
- [ ] CORS 정책 (허용 Origin 화이트리스트)
