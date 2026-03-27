# Hotel AX 솔루션 — 수익 관리 요구사항 문서

> **작성 기준**: AI_Harness 4계층 프레임워크 (Design Principles → CPS → Linter Enforcement → Evaluation)
> **적용 도메인**: 수익 관리 (Revenue Management) — `hotel_operations_ax_domain.md` §3-5 기반
> **작성일**: 2026년 3월
> **버전**: v0.1

---

## 목차

1. [설계 원칙 (Design Principles)](#1-설계-원칙-design-principles)
2. [CPS 프레임워크 적용](#2-cps-프레임워크-적용)
   - 2-1. [데이터 사일로 → 의사결정 지연](#2-1-데이터-사일로--의사결정-지연)
   - 2-2. [수요 예측 부정확 → 기회 손실](#2-2-수요-예측-부정확--기회-손실)
3. [기능 요구사항](#3-기능-요구사항)
4. [비기능 요구사항](#4-비기능-요구사항)
5. [아키텍처 요구사항](#5-아키텍처-요구사항)
6. [평가 기준 (Evaluation)](#6-평가-기준-evaluation)
7. [구현 제약 및 린터 원칙](#7-구현-제약-및-린터-원칙)

---

## 1. 설계 원칙 (Design Principles)

> AI_Harness 원칙: **"코드 작성 전에 불변의 규칙을 수립하고, 구조 자체가 품질을 보장한다."**

아래 원칙은 수익 관리 AX 솔루션 전체에 걸쳐 변경 불가한 기준으로 적용됩니다.

### P-1. AI는 보조한다, 결정은 사람이 한다

AI는 데이터 기반 권고(Recommendation)를 생성하되, 최종 요율 변경·채널 배분·LOS 설정은 반드시 Revenue Manager의 승인을 거친다.
자동 적용(Auto-apply)은 명시적으로 허용된 저위험 영역에 한정한다.

### P-2. 권고는 반드시 근거와 함께 제공된다

모든 AI 권고에는 참조 데이터 출처(경쟁사 요율, 이벤트 정보, 과거 실적)와 신뢰도 수준이 함께 출력된다.
근거 없는 권고는 시스템이 반환하지 않는다.

### P-3. 예측은 추적되고 검증된다

시스템이 생성한 모든 수요 예측은 날짜·입력 신호·예측값을 함께 저장한다.
실적 데이터가 수집되면 예측 오차(MAPE)를 자동 계산하여 모델 신뢰도를 지속 갱신한다.

### P-4. 외부 데이터는 정제 후 사용된다

외부 API(이벤트, 날씨, 항공)로부터 수집된 원시 데이터는 반드시 정규화·검증 단계를 거친 뒤 예측 모델에 입력된다.
결측·이상값이 있는 데이터는 권고 생성에서 제외하고 로그를 남긴다.

### P-5. 멱등성 — 동일한 입력은 동일한 권고를 생성한다

같은 시장 상황·같은 입력 신호에 대해 AI는 동일한 권고를 생성해야 한다.
LLM의 확률적 특성을 `temperature=0` 설정과 입력 정규화로 제어한다.

### P-6. 모델 독립성 — LLM 교체 시에도 워크플로우는 유지된다

LangGraph 노드와 비즈니스 로직은 특정 LLM에 종속되지 않는다.
OpenAI → 다른 LLM으로 전환 시 노드 내부 교체만으로 동일 워크플로우가 동작해야 한다.

---

## 2. CPS 프레임워크 적용

> AI_Harness CPS: **Context(배경) → Problem(핵심 문제) → Solution(해결책)**
> 비정형 고객 요구사항을 구조화하는 단계

---

### 2-1. 데이터 사일로 → 의사결정 지연

#### Context (배경)

- Revenue Manager는 PMS(객실 예약), OTA(채널별 요율), 경쟁사 요율을 각기 다른 시스템에서 수동으로 확인한다
- 데이터 취합에 평균 1~2시간 소요, 이 사이 시장 상황이 변화한다
- 현재 의사결정은 경험과 직감에 의존하며, 판단 근거가 기록되지 않는다
- 도메인 문서 기준: **"50%의 호텔이 수익·운영 의사결정 데이터에 접근 불가"** (§2 핵심 지표)

#### Problem (핵심 문제)

```
[분산된 데이터 소스]
  PMS 재고 현황 ─┐
  OTA 채널 요율  ─┼─ 수동 취합 (1~2h) ─→ 판단 지연 ─→ 실기(失機)
  경쟁사 요율   ─┘

[기록 부재]
  판단 근거 미기록 ─→ 반복 실수 ─→ 학습 불가
```

- **P1**: 데이터가 실시간으로 통합되지 않아 의사결정 타이밍을 놓침
- **P2**: 판단 근거가 기록되지 않아 팀 내 지식이 축적되지 않음
- **P3**: Revenue Manager 부재 시 (야간·휴일) 적시 대응 불가

#### Solution (해결책)

**S1 — 통합 데이터 수집 레이어**

| 구성 | 내용 |
|------|------|
| 수집 대상 | PMS 재고, OTA 채널 요율, 경쟁사 실시간 요율 |
| 수집 방식 | LangGraph `DataCollectorAgent` (Tool 노드) |
| 저장소 | MySQL `rate_snapshots` 테이블 (정형) |
| 수집 주기 | 경쟁사 요율: 1시간 / PMS·OTA: 15분 |

**S2 — RAG 기반 Revenue Assistant**

Revenue Manager가 자연어로 질문하면, 통합된 데이터를 바탕으로 근거 포함 권고를 반환한다.

```
질문: "오늘 밤 잔여 38객실, 요율 조정이 필요한가?"
  ↓
[retrieve_market]  경쟁사 요율 + OTA 현황 조회 (ChromaDB + MySQL)
  ↓
[retrieve_history] 과거 동일 요일·이벤트 패턴 조회
  ↓
[generate_recommendation] 권고 생성 + 근거 출처 명시
  ↓
응답: "요율 +22% 권고. 근거: 경쟁사 A 매진, B +18%, 당일 픽업 3.2배"
```

**S3 — 의사결정 이력 기록**

Revenue Manager의 최종 결정(수락/거절/수정)과 실제 결과를 MySQL에 저장하여 팀 내 판단 기준을 누적한다.

---

### 2-2. 수요 예측 부정확 → 기회 손실

#### Context (배경)

- 로컬 이벤트(콘서트, 전시, 컨퍼런스), 날씨, 항공 데이터를 개인이 수동으로 확인한다
- 예측 도구는 엑셀 스프레드시트이며, 외부 신호를 반영하지 못한다
- 예측값과 실제 점유율의 차이를 추적하는 시스템이 없다
- 도메인 문서 기준: **"AI 예측 도입 시 RevPAR 최대 35% 개선"** (§2 핵심 지표)

#### Problem (핵심 문제)

```
[외부 신호 누락]
  로컬 이벤트 ─┐
  날씨 예보   ─┼─ 담당자 수동 확인 (불규칙) ─→ 예측 오차 ↑
  항공 데이터 ─┘

[정확도 추적 없음]
  예측값 생성 ─→ 실적 미비교 ─→ 모델 개선 불가 ─→ 반복 오차
```

- **P1**: 외부 신호가 체계적으로 수집되지 않아 이벤트 기간 수요를 과소/과대 예측
- **P2**: 예측 정확도를 측정하는 지표가 없어 개선 방향을 알 수 없음
- **P3**: 예측값과 실적의 괴리 원인을 사후 분석할 수 없음

#### Solution (해결책)

**S1 — 외부 신호 자동 수집 파이프라인**

| 신호 유형 | 데이터 소스 | 수집 주기 | 저장 위치 |
|---------|-----------|---------|---------|
| 로컬 이벤트 (콘서트·전시·컨퍼런스) | Ticketmaster API / SerpAPI | 일 1회 | MySQL `external_signals` |
| 날씨 예보 (3~7일) | OpenWeatherMap API | 일 2회 | MySQL `external_signals` |
| 항공 검색량·운항 현황 | Amadeus Travel API | 일 1회 | MySQL `external_signals` |
| 공휴일·연휴 캘린더 | 정적 데이터 + 연간 갱신 | 연 1회 | MySQL `holiday_calendar` |

**S2 — LangGraph 수요 예측 워크플로우**

```
START
  ↓
[collect_signals]    외부 신호 수집 및 정규화
  ↓
[retrieve_history]   과거 동일 기간 실적 + 유사 이벤트 패턴 조회
  ↓
[generate_forecast]  LLM 기반 점유율·ADR 예측 생성
  ↓
[store_forecast]     예측값·입력 신호·신뢰도를 MySQL에 저장
  ↓
[recommend_action]   요율·LOS·채널 믹스 권고 생성
  ↓
END
```

**S3 — 예측 정확도 추적 루프**

```sql
-- 예측 저장
occupancy_forecasts: target_date | predicted_occ | predicted_adr | signal_snapshot | created_at

-- 실적 수집 (PMS, D+1)
occupancy_actuals: target_date | actual_occ | actual_adr | recorded_at

-- 자동 계산 지표
forecast_accuracy: target_date | mape_occ | mape_adr | signal_quality_score
```

예측 정확도(MAPE)가 임계값(기본 15%) 초과 시 알림 발송 및 모델 파라미터 재검토 트리거

---

## 3. 기능 요구사항

### FR-1. 통합 데이터 수집

| ID | 요구사항 | 우선순위 |
|----|---------|--------|
| FR-1-1 | 경쟁사 요율을 1시간 단위로 자동 수집하여 `rate_snapshots` 테이블에 저장 | 높음 |
| FR-1-2 | 로컬 이벤트 정보를 일 1회 수집, 향후 30일 이벤트 목록을 `external_signals`에 저장 | 높음 |
| FR-1-3 | 날씨 예보(3일)를 일 2회 수집 | 중간 |
| FR-1-4 | 수집 실패 시 오류 로그 기록 및 알림 발송 (데이터 공백 방지) | 높음 |
| FR-1-5 | 수집된 원시 데이터에 정규화·이상값 검증 적용 (P-4 원칙) | 높음 |

### FR-2. Revenue Assistant (RAG 채팅)

| ID | 요구사항 | 우선순위 |
|----|---------|--------|
| FR-2-1 | Revenue Manager가 자연어로 시장 상황을 질의하면 데이터 기반 권고를 반환 | 높음 |
| FR-2-2 | 모든 권고에 참조 데이터 출처와 신뢰도 수준을 함께 제공 (P-2 원칙) | 높음 |
| FR-2-3 | 요율 조정 / LOS 설정 / 채널 배분 / 프로모션 실행 여부 4가지 의사결정을 지원 | 높음 |
| FR-2-4 | 권고 수락·거절·수정 여부를 기록하여 의사결정 이력 누적 | 중간 |
| FR-2-5 | 세션별 대화 이력 유지 (MemorySaver, MySQL 영속 저장) | 높음 |

### FR-3. 수요 예측

| ID | 요구사항 | 우선순위 |
|----|---------|--------|
| FR-3-1 | 향후 7·14·30일 점유율 및 ADR을 일 1회 자동 예측 | 높음 |
| FR-3-2 | 예측 생성 시 사용된 외부 신호 스냅샷을 함께 저장 (P-3 원칙) | 높음 |
| FR-3-3 | 실적 데이터 수집 후 MAPE를 자동 계산하여 `forecast_accuracy`에 저장 | 높음 |
| FR-3-4 | MAPE가 임계값(15%) 초과 시 자동 알림 발송 | 중간 |
| FR-3-5 | 과거 예측-실적 비교 리포트를 API로 조회 가능 | 중간 |

### FR-4. 데이터 관리

| ID | 요구사항 | 우선순위 |
|----|---------|--------|
| FR-4-1 | 호텔 운영 문서(SOP, 요율표, 계약서)를 `/api/v1/ingest`로 벡터 DB에 인제스트 | 높음 |
| FR-4-2 | 의사결정 이력 조회 `/api/v1/history/{session_id}` | 높음 |
| FR-4-3 | 예측 정확도 리포트 조회 `/api/v1/forecast/accuracy` | 중간 |
| FR-4-4 | 외부 신호 현황 조회 `/api/v1/signals/current` | 중간 |

---

## 4. 비기능 요구사항

### NFR-1. 응답 성능

| 항목 | 목표값 |
|------|--------|
| Revenue Assistant 응답 시간 | 평균 5초 이내 |
| 외부 신호 수집 지연 | 스케줄 기준 ±5분 이내 |
| 예측 생성 완료 시간 | 1회 실행 기준 60초 이내 |

### NFR-2. 신뢰성

| 항목 | 목표값 |
|------|--------|
| API 가용성 | 99.5% 이상 |
| 외부 API 수집 실패 시 | 최대 3회 재시도 후 폴백 (이전 수집값 사용) |
| DB 연결 끊김 시 | SQLAlchemy `pool_pre_ping` + 자동 재연결 |

### NFR-3. 확장성

| 항목 | 기준 |
|------|------|
| 복수 호텔 지원 | `hotel_id` 기반 멀티 테넌트 구조로 설계 |
| 외부 API 추가 | LangGraph Tool 노드 단위 추가로 확장 |
| LLM 교체 | LangGraph 노드 내부만 교체, 워크플로우 유지 (P-6 원칙) |

### NFR-4. 보안

| 항목 | 기준 |
|------|------|
| API 키 관리 | 환경 변수(.env)만 사용, 코드에 하드코딩 금지 |
| 외부 API 응답 | 원시 데이터 저장 전 검증 필수 |
| DB 접근 | SQLAlchemy ORM 사용, Raw SQL 직접 실행 금지 |

---

## 5. 아키텍처 요구사항

### 5-1. LangGraph 그래프 구조

```
Revenue Assistant Graph
  START
    ↓
  [retrieve_market]     경쟁사 요율 + OTA 현황 (ChromaDB + MySQL)
    ↓
  [retrieve_history]    과거 동일 조건 실적 + 예측 정확도 (MySQL)
    ↓
  [generate_recommendation]  권고 + 근거 생성 (LLM)
    ↓
  END

Signal Collection Graph (스케줄 실행)
  START
    ↓
  [collect_events]   이벤트 API
  [collect_weather]  날씨 API      (병렬 실행)
  [collect_flights]  항공 API
    ↓
  [normalize_signals]  정규화·검증
    ↓
  [store_signals]      MySQL 저장
    ↓
  END

Forecast Graph (일 1회 실행)
  START
    ↓
  [load_signals]       최신 외부 신호 로드
    ↓
  [retrieve_history]   유사 기간 실적 조회
    ↓
  [generate_forecast]  점유율·ADR 예측
    ↓
  [store_forecast]     MySQL 저장
    ↓
  [generate_recommendation]  요율 권고 생성
    ↓
  END
```

### 5-2. MySQL 테이블 구조 (추가 필요)

```
기존 테이블
  chat_sessions
  chat_messages

신규 추가 테이블
  rate_snapshots        경쟁사·OTA 요율 이력
  external_signals      이벤트·날씨·항공 수집 데이터
  holiday_calendar      공휴일·연휴 기준 데이터
  occupancy_forecasts   AI 수요 예측값
  occupancy_actuals     PMS 실적 데이터
  forecast_accuracy     예측 vs 실적 오차 계산값
  decision_history      Revenue Manager 의사결정 이력
```

### 5-3. 역할 분담

| 저장소 | 저장 데이터 | 용도 |
|--------|-----------|------|
| **MySQL** | 정형 데이터 (요율, 예측, 실적, 이력) | 집계·조회·정확도 계산 |
| **ChromaDB** | 비정형 문서 (SOP, 보고서, 계약서) | 자연어 검색·RAG |
| **MemorySaver** | 세션 중 대화 이력 | LangGraph 상태 관리 |

---

## 6. 평가 기준 (Evaluation)

> AI_Harness 원칙: **"AI 에이전트 성능을 조직의 위험도 허용치에 맞게 지속적으로 모니터링한다."**

### 6-1. RAG 품질 메트릭

| 지표 | 설명 | 목표값 |
|------|------|--------|
| **Faithfulness** | 권고가 참조 문서에 근거하는 비율 | ≥ 0.85 |
| **Answer Relevancy** | 답변이 질문과 관련된 정도 | ≥ 0.80 |
| **Context Precision** | 검색된 컨텍스트의 관련성 | ≥ 0.75 |
| **Context Recall** | 필요한 컨텍스트를 빠짐없이 검색하는 비율 | ≥ 0.70 |

평가 도구: [RAGAS](https://github.com/explodinggradients/ragas)

### 6-2. 비즈니스 메트릭

| 지표 | 측정 방법 | 목표값 |
|------|---------|--------|
| **예측 정확도 (MAPE)** | `\|예측값 - 실적\| / 실적` 평균 | ≤ 10% (점유율), ≤ 8% (ADR) |
| **권고 수락률** | 수락된 권고 / 전체 권고 | ≥ 70% |
| **데이터 수집 성공률** | 성공한 수집 / 전체 스케줄 | ≥ 95% |
| **RevPAR 개선율** | 도입 전후 비교 | ≥ 10% (6개월 기준) |

### 6-3. 시스템 메트릭

| 지표 | 측정 방법 | 목표값 |
|------|---------|--------|
| **P95 응답 시간** | API 응답 분포 95번째 백분위 | ≤ 8초 |
| **오류율** | 5xx 응답 / 전체 요청 | ≤ 0.5% |
| **신호 수집 지연** | 스케줄 예정 시각 vs 실제 완료 시각 | ≤ 5분 |

### 6-4. 평가 주기

| 주기 | 평가 항목 |
|------|---------|
| **실시간** | API 응답시간, 오류율 |
| **일 1회** | 수집 성공률, 예측 MAPE |
| **주 1회** | 권고 수락률, RAG 품질 샘플 평가 |
| **월 1회** | RevPAR 개선율, 전체 모델 성능 리뷰 |

---

## 7. 구현 제약 및 린터 원칙

> AI_Harness 원칙: **"프롬프팅만으로는 일관성을 보장할 수 없다. 자동화된 규칙으로 최종 보장한다."**

### 7-1. 코드 구조 원칙

```
app/
  api/routes/       엔드포인트 정의만 (비즈니스 로직 금지)
  rag/              LangGraph 그래프·노드 정의
  database/         ORM 모델·CRUD만 (Raw SQL 금지)
  core/             설정·공통 유틸리티
  agents/           외부 신호 수집 에이전트 (신규)
  models/           Pydantic 스키마 (입출력 검증)
```

### 7-2. LangGraph 노드 작성 규칙

- 노드 함수는 `state: RAGState → dict` 시그니처를 준수한다
- 노드 하나의 책임은 하나다 (SRP — Single Responsibility)
- 외부 API 호출은 `agents/` 디렉토리의 Tool 함수로 분리한다
- LLM 직접 호출은 `generate_*` 접두사 노드에서만 허용한다

### 7-3. 데이터 계층 원칙

- 모든 DB 접근은 `app/database/crud.py` 함수를 통한다
- 라우트·노드에서 `Session` 직접 쿼리 금지
- 외부 API 응답은 Pydantic 모델로 파싱 후 저장한다
- 환경 변수는 `app/core/config.py` `Settings` 클래스를 통해서만 참조한다

### 7-4. 에러 처리 원칙

- 외부 API 실패: 최대 3회 재시도 → 폴백(이전 데이터) → 로그 기록
- LLM 실패: HTTP 500 반환 + 오류 상세 로그 기록
- 수집 오류가 예측 생성을 차단하지 않는다 (데이터 공백 시 신뢰도 하향 표시)

---

## 부록. 구현 로드맵

| Phase | 내용 | 기준 완료 조건 |
|-------|------|-------------|
| **Phase 1** | MySQL 테이블 추가 (rate_snapshots, external_signals, occupancy_forecasts 등) | 스키마 마이그레이션 완료 |
| **Phase 2** | 외부 신호 수집 에이전트 구현 (날씨·이벤트부터 시작) | 수집 성공률 ≥ 95% |
| **Phase 3** | LangGraph 수요 예측 워크플로우 구현 | MAPE ≤ 15% (초기 기준) |
| **Phase 4** | Revenue Assistant RAG 고도화 (시장 데이터 연동) | 권고 수락률 ≥ 60% |
| **Phase 5** | PMS·OTA 실제 API 연동 | 데이터 사일로 완전 해소 |
| **Phase 6** | RAGAS 기반 자동 평가 파이프라인 구축 | 주간 품질 리포트 자동화 |

---

*참조 문서: `hotel_operations_ax_domain.md`, AI_Harness (github.com/arslanRedemar/AI_Harness)*
