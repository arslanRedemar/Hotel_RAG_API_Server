# Plan: System Common 구현 계획

> **요구사항 참조**: [system_common.md](../requirements/system_common.md)
> **우선순위**: P0 (전체 시스템의 기반)
> **설명**: 인증, 로깅, 모니터링, 배포 등 모든 기능 모듈이 공통으로 사용하는 기반 시스템

---

## 1. 현재 상태 및 Gap

### 현재 구현
| 항목 | 상태 | 파일 |
|------|------|------|
| FastAPI 기본 서버 | ✅ | `main.py` |
| MySQL 연결 (SQLAlchemy) | ✅ | `app/database/connection.py` |
| Docker + docker-compose | ✅ | `Dockerfile`, `docker-compose.yml` |
| 환경 변수 관리 (.env) | ✅ | `app/core/config.py` |
| CORS 설정 | ✅ | `main.py` |
| 헬스 체크 엔드포인트 | ✅ | `main.py` |
| JWT 인증, 역할 기반 권한 | ✅ | `app/auth/` |
| 알림 시스템 (Email/Web Push) | ✅ | `app/notifications/` |
| 파일 저장소 (업로드/Presigned URL) | ✅ | `app/storage/service.py` |
| 감사 로그 (불변) | ✅ | `app/audit/logger.py` |
| Circuit Breaker | ✅ | `app/core/circuit_breaker.py` |
| 구조화된 로그 + 메트릭 미들웨어 | ✅ | `app/core/logging.py`, `app/core/middleware.py` |
| LLM 라우터 (로컬/클라우드) | ✅ | `app/core/llm_router.py` |
| 임베딩 프로바이더 전환 | ✅ | `app/core/embedding_router.py` |
| LLM 비용 모니터링 | ✅ | `app/core/cost_monitor.py` |

### 미구현 (Gap)
| 요구사항 ID | 내용 | 우선순위 |
|------------|------|---------|
| SYS-F53 | CI 파이프라인 (자동 테스트) | P1 |
| SYS-F74 | 로컬 모델 폴백률 Prometheus 메트릭 노출 | P2 |
| SYS-F44 | LLM 비용 월 예산 알림 — Slack/이메일 연동 | P1 |

---

## 2. 전체 공통 모듈 구조

```
app/
├── auth/                    # 신규: 인증 시스템
│   ├── __init__.py
│   ├── jwt.py               # JWT 생성/검증
│   ├── password.py          # bcrypt 해싱
│   └── dependencies.py      # FastAPI Depends
│
├── core/
│   ├── config.py            # 수정: 추가 환경 변수
│   ├── logging.py           # 신규: 구조화된 로그
│   ├── middleware.py         # 신규: 로깅/메트릭 미들웨어
│   └── circuit_breaker.py   # 신규: Circuit Breaker
│
├── notifications/           # 신규: 알림 시스템
│   ├── __init__.py
│   ├── service.py           # 알림 서비스 (채널 통합)
│   ├── email.py             # SMTP 이메일
│   ├── push.py              # Web Push
│   └── templates/           # 이메일 HTML 템플릿
│
├── storage/                 # 신규: 파일 저장소
│   ├── __init__.py
│   └── service.py           # 로컬/S3 저장소
│
├── audit/                   # 신규: 감사 로그
│   ├── __init__.py
│   └── logger.py            # 불변 감사 로그 기록
│
└── database/
    └── models.py            # 수정: User, AuditLog, PushSubscription 추가
```

---

## 3. 구현 상세

### 3-1. 구조화된 로깅 (SYS-F61)

```python
# app/core/logging.py

import logging
import json
import sys
from datetime import datetime

class JSONFormatter(logging.Formatter):
    """JSON Lines 형태 구조화 로그"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 추가 컨텍스트 (request_id, user_id 등)
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)

def setup_logging():
    """애플리케이션 로깅 설정"""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # stdout 핸들러 (Docker 컨테이너 로그 수집용)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)

    # 외부 라이브러리 로그 레벨 억제
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
```

### 3-2. 요청/응답 미들웨어 (SYS-F62)

```python
# app/core/middleware.py

import time
import uuid
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("app.middleware")

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """모든 HTTP 요청/응답을 구조화된 로그로 기록"""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())[:8]
        start_time = time.perf_counter()

        # 요청 로그
        logger.info(
            "HTTP 요청 시작",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host if request.client else "unknown",
            }
        )

        # 요청에 request_id 주입 (하위 핸들러에서 접근 가능)
        request.state.request_id = request_id

        response = await call_next(request)

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # 응답 로그
        log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            log_level,
            "HTTP 응답 완료",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            }
        )

        # 응답 헤더에 request_id 추가 (디버깅용)
        response.headers["X-Request-ID"] = request_id

        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """API 메트릭 수집 (Prometheus 연동 준비)"""

    def __init__(self, app, metrics_registry=None):
        super().__init__(app)
        self.request_count = {}
        self.total_duration = {}
        self.error_count = {}

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method
        key = f"{method}:{path}"

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        # 메트릭 업데이트 (인메모리, 실제는 Prometheus 클라이언트 사용)
        self.request_count[key] = self.request_count.get(key, 0) + 1
        self.total_duration[key] = self.total_duration.get(key, 0) + duration_ms
        if response.status_code >= 400:
            self.error_count[key] = self.error_count.get(key, 0) + 1

        return response
```

### 3-3. Circuit Breaker (SYS-F41)

```python
# app/core/circuit_breaker.py

import time
from enum import Enum
from dataclasses import dataclass, field
from functools import wraps

class CircuitState(Enum):
    CLOSED = "closed"        # 정상 동작
    OPEN = "open"            # 차단 (장애 감지)
    HALF_OPEN = "half_open"  # 회복 시도 중

@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5      # 연속 실패 N회 시 OPEN
    recovery_timeout: int = 60      # OPEN 상태 유지 시간 (초)
    success_threshold: int = 2      # HALF_OPEN에서 성공 N회 시 CLOSED

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = field(default_factory=float)

    def call(self, func, *args, **kwargs):
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
            else:
                raise CircuitOpenError(f"Circuit {self.name} is OPEN")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0

    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN

class CircuitOpenError(Exception):
    pass

# 싱글톤 Circuit Breaker 레지스트리
_breakers: dict[str, CircuitBreaker] = {}

def get_circuit_breaker(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name=name)
    return _breakers[name]

# 사용 예시
def with_circuit_breaker(breaker_name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            breaker = get_circuit_breaker(breaker_name)
            return breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator

# OpenAI 호출에 적용
@with_circuit_breaker("openai_api")
def call_openai_llm(messages, **kwargs):
    # OpenAI API 호출
    pass
```

### 3-4. 파일 저장소 (SYS-F20~23)

```python
# app/storage/service.py

import os
import uuid
import hmac
import hashlib
import time
from pathlib import Path
from fastapi import UploadFile

class FileStorageService:
    """로컬 스토리지 (초기), S3 호환 스토리지 (향후 전환)"""

    def __init__(self, base_path: str = "./data/uploads"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    ALLOWED_TYPES = {
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "image/jpeg": ".jpg",
        "image/png": ".png",
    }
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

    async def save(self, file: UploadFile, subfolder: str = "") -> dict:
        """파일 저장 + 경로 반환"""
        # 파일 형식 검증
        if file.content_type not in self.ALLOWED_TYPES:
            raise ValueError(f"지원하지 않는 파일 형식: {file.content_type}")

        # 파일 크기 검증
        content = await file.read()
        if len(content) > self.MAX_FILE_SIZE:
            raise ValueError("파일 크기가 50MB를 초과합니다")

        # 안전한 파일명 생성 (UUID)
        extension = self.ALLOWED_TYPES[file.content_type]
        filename = f"{uuid.uuid4().hex}{extension}"

        # 서브폴더 구성
        save_dir = self.base_path / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        file_path = save_dir / filename

        # 저장
        with open(file_path, "wb") as f:
            f.write(content)

        return {
            "file_path": str(file_path),
            "file_name": file.filename,  # 원본 파일명 별도 저장
            "file_size_bytes": len(content),
            "file_type": extension.lstrip("."),
            "storage_key": f"{subfolder}/{filename}" if subfolder else filename,
        }

    def generate_presigned_url(self, storage_key: str, expires_in: int = 3600) -> str:
        """서명된 임시 URL 생성 (외부 노출 금지)"""
        from app.core.config import settings

        expire_ts = int(time.time()) + expires_in
        message = f"{storage_key}:{expire_ts}"
        signature = hmac.new(
            settings.secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()[:16]

        return f"/api/v1/files/{storage_key}?exp={expire_ts}&sig={signature}"

    def validate_presigned_url(self, storage_key: str, exp: int, sig: str) -> bool:
        """Presigned URL 유효성 검증"""
        from app.core.config import settings

        if time.time() > exp:
            return False  # 만료

        message = f"{storage_key}:{exp}"
        expected_sig = hmac.new(
            settings.secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()[:16]

        return hmac.compare_digest(sig, expected_sig)

    def soft_delete(self, storage_key: str):
        """소프트 삭제 (30일 후 실제 삭제)"""
        file_path = self.base_path / storage_key
        if file_path.exists():
            deleted_path = self.base_path / "deleted" / storage_key
            deleted_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.rename(deleted_path)

            # 30일 후 삭제 스케줄 (Celery)
            from app.tasks.cleanup_tasks import cleanup_deleted_file
            cleanup_deleted_file.apply_async(
                args=[str(deleted_path)],
                countdown=30 * 24 * 60 * 60  # 30일
            )
```

### 3-5. 감사 로그 (SYS-F30~33)

```sql
-- 감사 로그 테이블 (별도 DB 또는 읽기 전용 권한으로 관리)
CREATE TABLE audit_logs (
    id              BIGINT   PRIMARY KEY AUTO_INCREMENT,
    action          VARCHAR(50) NOT NULL,  -- 'CREATE', 'UPDATE', 'DELETE', 'LOGIN'
    entity_type     VARCHAR(100) NOT NULL, -- 'work_order', 'sop', 'user', ...
    entity_id       VARCHAR(100),
    actor_id        INT,                   -- NULL이면 시스템
    actor_email     VARCHAR(255),          -- 스냅샷 (사용자 삭제 후도 보존)
    ip_address      VARCHAR(50),
    before_value    JSON,                  -- 변경 전
    after_value     JSON,                  -- 변경 후
    metadata        JSON,                  -- 추가 컨텍스트
    occurred_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_entity (entity_type, entity_id),
    INDEX idx_actor (actor_id),
    INDEX idx_occurred_at (occurred_at)
) ENGINE=InnoDB;
-- 주의: 이 테이블의 DELETE 권한은 제거하고 애플리케이션 계정에서 INSERT/SELECT만 허용
```

```python
# app/audit/logger.py

import logging
from datetime import datetime
from app.database.connection import get_audit_db  # 감사 로그 전용 세션

audit_logger = logging.getLogger("audit")

class AuditLogger:
    def log(
        self,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        actor_id: int | None = None,
        actor_email: str | None = None,
        before_value: dict | None = None,
        after_value: dict | None = None,
        metadata: dict | None = None,
        ip_address: str | None = None,
    ):
        record = {
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_id": actor_id,
            "actor_email": actor_email,
            "ip_address": ip_address,
            "before_value": before_value,
            "after_value": after_value,
            "metadata": metadata,
            "occurred_at": datetime.utcnow(),
        }

        # DB 저장
        try:
            with get_audit_db() as db:
                db.execute(
                    "INSERT INTO audit_logs (action, entity_type, entity_id, actor_id, actor_email, "
                    "ip_address, before_value, after_value, metadata, occurred_at) "
                    "VALUES (:action, :entity_type, :entity_id, :actor_id, :actor_email, "
                    ":ip_address, :before_value, :after_value, :metadata, :occurred_at)",
                    record
                )
                db.commit()
        except Exception as e:
            # 감사 로그 저장 실패는 파일 로그에 백업
            audit_logger.error(f"감사 로그 DB 저장 실패: {e}. 데이터: {record}")

# 싱글톤
audit_log = AuditLogger()

# 사용 예시 (Work Order 생성 시)
def create_work_order(data: dict, current_user: User) -> dict:
    wo = _save_to_db(data)
    audit_log.log(
        action="CREATE",
        entity_type="work_order",
        entity_id=wo["id"],
        actor_id=current_user.id,
        actor_email=current_user.email,
        after_value=wo,
    )
    return wo
```

---

### 3-6. LLM 라우터 (SYS-F70~75)

```python
# app/core/llm_router.py
from enum import IntEnum
from langchain_community.chat_models import ChatOllama
from langchain_openai import ChatOpenAI
from app.core.config import settings

class TaskTier(IntEnum):
    """
    Tier 1: 로컬 전용  — OCR, 분류, 임베딩 (SYS-F70)
    Tier 2: 로컬 우선  — 구조 추출, 단순 RAG (SYS-F71)
    Tier 3: 클라우드   — 복합 추론, 멀티소스 RAG (SYS-F72)
    """
    LOCAL_ONLY = 1
    LOCAL_FIRST = 2
    CLOUD_FIRST = 3


class LLMRouter:
    """SYS-F70: 작업 유형별 로컬/클라우드 자동 라우팅"""

    def __init__(self):
        self._local = ChatOllama(
            model=settings.local_llm_model,          # e.g. "qwen2.5:3b"
            base_url=settings.local_llm_endpoint,    # e.g. "http://localhost:11434"
            temperature=0,
        )
        self._cloud = ChatOpenAI(
            model=settings.llm_model,                # e.g. "gpt-4o-mini"
            api_key=settings.openai_api_key,
            temperature=0,
        )
        self.threshold: float = settings.local_llm_confidence_threshold  # default 0.70

    def get_llm(self, tier: TaskTier):
        """Tier에 따라 적절한 LLM 반환"""
        if tier == TaskTier.CLOUD_FIRST:
            return self._cloud
        return self._local  # Tier 1/2는 로컬 우선

    def get_fallback(self, tier: TaskTier):
        """Tier 2는 낮은 confidence 시 클라우드 폴백 반환"""
        if tier == TaskTier.LOCAL_FIRST:
            return self._cloud
        return None  # Tier 1은 폴백 없음

    def should_fallback(self, confidence: float) -> bool:
        return confidence < self.threshold


# 싱글톤
llm_router = LLMRouter()
```

```python
# app/core/embedding_router.py
from langchain_community.embeddings import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings
from app.core.config import settings


def get_embeddings():
    """
    RAG-F16: 환경변수 EMBEDDING_PROVIDER에 따라 로컬/클라우드 임베딩 선택
    - local  : nomic-embed-text-v1.5 via Ollama (기본값)
    - openai : text-embedding-3-small
    """
    provider = settings.embedding_provider.lower()
    if provider == "openai":
        return OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.openai_api_key,
        )
    # 기본값: 로컬 Ollama 임베딩
    return OllamaEmbeddings(
        model=settings.local_embedding_model,   # e.g. "nomic-embed-text"
        base_url=settings.local_llm_endpoint,
    )
```

```python
# app/core/config.py 추가 필드 (Pydantic Settings)

class Settings(BaseSettings):
    # ... 기존 필드 ...

    # ===== 로컬 LLM (SYS-F70) =====
    local_llm_endpoint: str = "http://localhost:11434"
    local_llm_model: str = "qwen2.5:3b"           # Tier 2 구조 추출
    local_ocr_model: str = "deepseek-vl2"          # Tier 1 OCR (Ollama)
    local_classifier_model: str = "phi3:mini"      # Tier 1 분류
    local_embedding_model: str = "nomic-embed-text" # Tier 1 임베딩
    local_llm_confidence_threshold: float = 0.70   # 폴백 트리거 기준

    # ===== 임베딩 프로바이더 (RAG-F16) =====
    embedding_provider: str = "local"              # "local" | "openai"
```

```python
# app/core/cost_monitor.py (SYS-F72~73)
import logging
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)

@dataclass
class TokenUsage:
    module: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

_usage_store: dict[str, TokenUsage] = {}
_lock = Lock()

def record_usage(module: str, prompt_tokens: int, completion_tokens: int, model: str = "gpt-4o-mini"):
    """SYS-F72: 모듈별 토큰 사용량 기록"""
    # gpt-4o-mini: $0.15/1M input, $0.60/1M output
    PRICE = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (5.0, 15.0)}
    in_p, out_p = PRICE.get(model, (0.15, 0.60))
    cost = (prompt_tokens * in_p + completion_tokens * out_p) / 1_000_000

    with _lock:
        if module not in _usage_store:
            _usage_store[module] = TokenUsage(module=module)
        u = _usage_store[module]
        u.prompt_tokens += prompt_tokens
        u.completion_tokens += completion_tokens
        u.cost_usd += cost

    # SYS-F73: 월 예산 80% 초과 시 알림
    _check_budget_alert()

def get_usage_summary() -> list[dict]:
    """SYS-F72: 대시보드용 집계"""
    with _lock:
        return [
            {
                "module": u.module,
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
                "total_tokens": u.prompt_tokens + u.completion_tokens,
                "cost_usd": round(u.cost_usd, 4),
            }
            for u in _usage_store.values()
        ]

def _check_budget_alert():
    from app.core.config import settings
    total_cost = sum(u.cost_usd for u in _usage_store.values())
    budget = getattr(settings, "monthly_llm_budget_usd", 0)
    if budget > 0 and total_cost >= budget * 0.8:
        logger.warning(f"[SYS-F73] LLM 월 예산 80% 도달: ${total_cost:.2f} / ${budget:.2f}")
```

---

## 4. 헬스 체크 개선 (SYS-F60)

```python
# main.py

@app.get("/health")
async def health(db: Session = Depends(get_db)):
    checks = {}

    # DB 연결 확인
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"

    # ChromaDB 연결 확인
    try:
        from app.rag.vector_store import get_vector_store
        vs = get_vector_store()
        vs._collection.count()
        checks["vector_store"] = "ok"
    except Exception as e:
        checks["vector_store"] = f"error: {str(e)}"

    # Redis 연결 확인 (Celery 브로커)
    try:
        import redis
        r = redis.from_url(settings.redis_url)
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"

    return {
        "status": overall,
        "version": "0.2.0",
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
```

---

## 5. 환경 변수 전체 목록 (개정판)

```bash
# .env.example (전체 변수 목록)

# ===== 서버 =====
APP_HOST=0.0.0.0
APP_PORT=8000
DEBUG=false
HOTEL_NAME=호텔명

# ===== 보안 =====
SECRET_KEY=                    # openssl rand -hex 32
ACCESS_TOKEN_EXPIRE_MINUTES=60
QR_SECRET=                     # Guest QR 서명용 별도 시크릿

# ===== OpenAI =====
OPENAI_API_KEY=
LLM_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small

# ===== 로컬 LLM / Ollama (SYS-F70) =====
LOCAL_LLM_ENDPOINT=http://localhost:11434
LOCAL_LLM_MODEL=qwen2.5:3b
LOCAL_OCR_MODEL=deepseek-vl2
LOCAL_CLASSIFIER_MODEL=phi3:mini
LOCAL_EMBEDDING_MODEL=nomic-embed-text
LOCAL_LLM_CONFIDENCE_THRESHOLD=0.70   # 0.0~1.0, 이 값 미만이면 클라우드 폴백

# ===== 임베딩 프로바이더 (RAG-F16) =====
EMBEDDING_PROVIDER=local               # "local" | "openai"

# ===== LLM 비용 모니터링 (SYS-F73) =====
MONTHLY_LLM_BUDGET_USD=50.0            # 월 예산 (0이면 알림 비활성화)

# ===== Vector Store =====
CHROMA_PERSIST_DIR=./data/chroma_db

# ===== RAG 파라미터 =====
CHUNK_SIZE=500
CHUNK_OVERLAP=50
TOP_K_RESULTS=5

# ===== MySQL =====
MYSQL_URL=mysql+pymysql://root:password@localhost:3306/hotel_rag
MYSQL_ROOT_PASSWORD=password
MYSQL_DATABASE=hotel_rag

# ===== Redis (Celery) =====
REDIS_URL=redis://localhost:6379/0

# ===== 파일 저장소 =====
FILE_STORAGE_PATH=./data/uploads

# ===== 이메일 (SMTP) =====
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=noreply@hotel.com
SMTP_PASSWORD=

# ===== Web Push (VAPID) =====
VAPID_PRIVATE_KEY=
VAPID_PUBLIC_KEY=

# ===== PMS 연동 =====
PMS_BASE_URL=
PMS_API_KEY=

# ===== OCR =====
GOOGLE_VISION_API_KEY=         # Google Vision OCR 사용 시 (선택)

# ===== 외부 API =====
CULTURE_API_KEY=               # 문화체육관광부 공공 API
WEATHER_API_KEY=               # 날씨 API

# ===== 모니터링 =====
TOTAL_ROOMS=200                # 전체 객실 수
```

---

## 6. docker-compose.yml 전체 개정

```yaml
version: '3.9'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - MYSQL_URL=mysql+pymysql://root:${MYSQL_ROOT_PASSWORD}@mysql:3306/${MYSQL_DATABASE}
      - REDIS_URL=redis://redis:6379/0
    env_file:
      - .env
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  celery_worker:
    build: .
    command: celery -A app.tasks worker --loglevel=info --concurrency=4
    env_file:
      - .env
    environment:
      - MYSQL_URL=mysql+pymysql://root:${MYSQL_ROOT_PASSWORD}@mysql:3306/${MYSQL_DATABASE}
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - api
      - redis
    volumes:
      - ./data:/app/data
    restart: unless-stopped

  celery_beat:
    build: .
    command: celery -A app.tasks beat --loglevel=info --scheduler celery.beat:PersistentScheduler
    env_file:
      - .env
    environment:
      - MYSQL_URL=mysql+pymysql://root:${MYSQL_ROOT_PASSWORD}@mysql:3306/${MYSQL_DATABASE}
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    restart: unless-stopped

  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: ${MYSQL_DATABASE}
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
      - ./scripts/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

volumes:
  mysql_data:
  redis_data:
```

---

## 7. CI/CD 파이프라인 (GitHub Actions, SYS-F53)

```yaml
# .github/workflows/ci.yml

name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      mysql:
        image: mysql:8.0
        env:
          MYSQL_ROOT_PASSWORD: testpass
          MYSQL_DATABASE: hotel_rag_test
        ports: ["3306:3306"]
        options: >-
          --health-cmd="mysqladmin ping"
          --health-interval=10s

      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio pytest-cov

      - name: Install Tesseract
        run: |
          sudo apt-get update
          sudo apt-get install -y tesseract-ocr tesseract-ocr-kor poppler-utils

      - name: Run tests
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          MYSQL_URL: mysql+pymysql://root:testpass@localhost:3306/hotel_rag_test
          REDIS_URL: redis://localhost:6379/0
          SECRET_KEY: test-secret-key-32-characters-here
        run: |
          pytest tests/ -v --cov=app --cov-report=xml --cov-fail-under=70

      - name: Upload coverage
        uses: codecov/codecov-action@v4

  docker-build:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t hotel-rag-api:test .
```

---

## 8. 구현 체크리스트

### P0 (최우선 — 모든 기능의 전제)
- [ ] `app/auth/` 모듈 완성 (JWT, bcrypt, Depends)
- [ ] `users`, `departments` DB 테이블 + 시드 데이터
- [ ] 모든 기존 API에 인증 미들웨어 적용
- [ ] `app/storage/service.py` 파일 저장소 구현
- [ ] `audit_logs` 테이블 + `AuditLogger` 구현
- [ ] `app/core/logging.py` JSON 구조화 로그 적용

### P1 (기능 확장 단계)
- [ ] `app/notifications/` 이메일/푸시 알림 모듈
- [ ] `app/core/circuit_breaker.py` OpenAI API에 적용
- [ ] `app/core/middleware.py` 요청 로그 + 메트릭 미들웨어
- [ ] `.github/workflows/ci.yml` CI 파이프라인 설정
- [ ] `docker-compose.yml` Redis + Celery 서비스 추가
- [ ] `GET /health` 전체 서브시스템 체크 개선
- [ ] `app/core/llm_router.py` LLMRouter 구현 (SYS-F70)
- [ ] `app/core/embedding_router.py` 임베딩 프로바이더 전환 (RAG-F16)
- [ ] `app/core/cost_monitor.py` 모듈별 토큰 사용량 기록 (SYS-F72)
- [ ] `GET /admin/llm-cost` LLM 비용 대시보드 API (SYS-F72)
- [ ] Ollama 서비스 `docker-compose.yml` 추가 (Tier 1/2 모델 서빙)

### P2 (운영 성숙도)
- [ ] Prometheus 메트릭 엔드포인트 (`/metrics`)
- [ ] Grafana 대시보드 구성
- [ ] 감사 로그 5년 아카이빙 전략 (S3 또는 별도 DB)
- [ ] Presigned URL 캐싱 (CDN 연동)
- [ ] LLM 비용 월 예산 80% 알림 (SYS-F73) — Slack/이메일 연동
- [ ] 로컬 모델 폴백률 Prometheus 메트릭 노출 (SYS-F74)
