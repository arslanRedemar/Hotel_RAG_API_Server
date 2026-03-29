# Hotel AX API Server — Claude Code Guide

## 프로젝트 개요

**Hotel AX (Automation for Excellence)** — 호텔 운영 자동화를 위한 RAG 기반 API 서버.
FastAPI + LangChain + ChromaDB 스택으로 구축되며, 5개 핵심 모듈로 구성됩니다.

| 모듈 | 설명 | 우선순위 |
|------|------|----------|
| RAG Assistant | 문서 기반 Q&A + 대화 히스토리 | P0 (완료) |
| SOP Digitalization | OCR + AI 추출 | P1 |
| Work Order Automation | AI 분류 + 자동 배정 | P1 |
| Compliance & Audit | 점검 스케줄링 + 이상 감지 | P1 |
| Revenue Management | 수요 예측 + AI 요율 추천 | P2 |

## 기술 스택

- **Backend**: Python 3.11, FastAPI 0.115+, Uvicorn
- **RAG/LLM**: LangChain 0.3+, LangGraph, OpenAI (gpt-4o-mini, text-embedding-3-small)
- **Vector DB**: ChromaDB (로컬 persistent)
- **RDBMS**: MySQL 8.0, SQLAlchemy 2.0, Alembic
- **Queue**: Celery 5.4 + Redis 7
- **Auth**: JWT (python-jose + passlib/bcrypt)
- **OCR**: pytesseract + opencv-python-headless
- **Notifications**: aiosmtplib (Email), pywebpush (Web Push)
- **ML/Forecasting**: Prophet, XGBoost, scikit-learn
- **Observability**: LangSmith (tracing via MCP)

## 디렉터리 구조

```
Hotel_RAG_API_Server/
├── main.py                  # FastAPI 진입점 (lifespan, middleware, router)
├── requirements.txt
├── docker-compose.yml       # API + Celery + MySQL + Redis
├── Dockerfile
├── .env.example             # 환경변수 템플릿
├── app/
│   ├── api/                 # REST 라우터
│   ├── core/                # config, logging, middleware, circuit_breaker
│   ├── auth/                # JWT 인증
│   ├── rag/                 # RAG 파이프라인 (chain.py, graph.py, vector_store.py)
│   ├── database/            # SQLAlchemy models, CRUD, connection, seed
│   ├── models/              # Pydantic 스키마
│   ├── notifications/       # Email, Web Push
│   ├── audit/               # 감사 로그
│   └── storage/             # 파일 스토리지 (S3/로컬)
├── data/                    # ChromaDB 저장소, 문서 파일
├── docs/                    # 요구사항·아키텍처·구현 계획 문서
└── tests/                   # pytest 테스트 스위트
```

## 개발 명령어

```bash
# 의존성 설치
pip install -r requirements.txt

# 로컬 서버 실행
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Docker 전체 스택 실행
docker-compose up --build

# 테스트 실행
pytest tests/ -v

# 커버리지 포함 테스트
pytest tests/ --cov=app --cov-report=term-missing

# DB 마이그레이션 생성
alembic revision --autogenerate -m "message"

# DB 마이그레이션 적용
alembic upgrade head
```

## 환경 설정

`.env.example`을 `.env`로 복사 후 아래 필수 값 설정:

```bash
# 최소 필수 (로컬 개발)
OPENAI_API_KEY=sk-...
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/hotel_ax
REDIS_URL=redis://localhost:6379/0
JWT_SECRET_KEY=<랜덤 32자 이상>

# LangSmith 트레이싱 (선택)
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=hotel-ax
```

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 서비스 상태 (DB, VectorStore, Redis) |
| GET | `/metrics` | API 메트릭 + Circuit Breaker 상태 |
| POST | `/api/v1/chat` | RAG 채팅 질의 |
| POST | `/api/v1/ingest` | 문서 인덱싱 |
| POST | `/auth/login` | JWT 로그인 |
| POST | `/auth/refresh` | 토큰 갱신 |

## 코딩 컨벤션

- **언어**: Python (타입 힌트 필수, `from __future__ import annotations` 불필요)
- **포맷터**: ruff (`.ruff_cache/` 존재, `ruff check . --fix` 사용)
- **비동기**: FastAPI 엔드포인트는 `async def`, 블로킹 I/O는 `run_in_executor` 사용
- **로깅**: `logging.getLogger(__name__)` 사용, `print()` 금지
- **설정**: 모든 설정값은 `app/core/config.py`의 `settings` 객체를 통해 접근
- **에러 처리**: HTTPException + 커스텀 예외 핸들러, 범용 `except Exception` 최소화

## 테스트 원칙 (tdd-workflow 스킬 적용)

- **TDD 필수**: 새 기능·버그픽스 시 테스트 먼저 작성
- **커버리지 목표**: 80% 이상 (unit + integration)
- **테스트 파일 위치**: `tests/test_<module>.py`
- **픽스처**: `conftest.py`에 DB 세션·앱 클라이언트 공용 픽스처 정의
- **외부 서비스 모킹**: OpenAI, ChromaDB, Redis는 `unittest.mock` 또는 `pytest-mock` 사용
- **통합 테스트**: `TestClient(app)` + 인메모리 SQLite 또는 테스트 DB 사용

```bash
# pytest 패턴
pytest tests/test_auth.py -v            # 특정 모듈
pytest tests/ -k "test_chat"            # 키워드 필터
pytest tests/ --cov=app --cov-fail-under=80  # 커버리지 강제
```

## 스킬

이 프로젝트에는 다음 Claude Code 스킬이 설치되어 있습니다:

| 스킬 | 설명 |
|------|------|
| `tdd-workflow` | TDD 워크플로 강제 (80%+ 커버리지) |
| `langchain-architecture` | LangChain/LangGraph 아키텍처 패턴 |
| `langchain-rag` | RAG 파이프라인 구축 |
| `langgraph-fundamentals` | LangGraph StateGraph 패턴 |
| `langgraph-persistence` | 대화 상태 지속성 (checkpointer) |
| `langsmith-trace` | LangSmith 트레이싱 |
| `github-actions-docs` | GitHub Actions 워크플로 작성·보안·트러블슈팅 |
| `ruff-linting` | ruff 린트 오류 자동 감지 및 수정 |

## MCP 서버

`.mcp.json`에 LangSmith MCP 서버가 설정되어 있습니다.
`LANGSMITH_API_KEY` 환경변수 설정 시 트레이스 조회·관리가 가능합니다.

## 아키텍처 문서

상세 설계는 `docs/` 디렉터리 참조:
- `docs/overview.md` — 전체 시스템 아키텍처
- `docs/requirements/` — 모듈별 요구사항 (6개 파일)
- `docs/plans/` — 구현 계획 (12개 파일)
- `docs/hotel_operations_ax_domain.md` — 호텔 도메인 지식
