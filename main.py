import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.router import api_router
from app.core.circuit_breaker import get_all_statuses
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.middleware import MetricsMiddleware, RequestLoggingMiddleware
from app.database.connection import create_tables, get_db

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Hotel AX API 서버 시작")
    create_tables()

    # 초기 시드 데이터 (관리자 계정, 부서)
    try:
        from app.database.connection import SessionLocal
        from app.database.seed import seed

        with SessionLocal() as db:
            seed(db)
    except Exception as exc:
        logger.warning(f"시드 데이터 초기화 실패 (무시): {exc}")

    yield
    logger.info("Hotel AX API 서버 종료")


app = FastAPI(
    title="Hotel AX API Server",
    description="호텔 운영 자동화(AX) RAG 기반 API 서버",
    version="0.2.0",
    lifespan=lifespan,
)

# ── 미들웨어 (등록 역순으로 실행) ────────────────────────────
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


# ── 헬스 체크 ────────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health(db: Session = Depends(get_db)):
    checks: dict[str, str] = {}

    # MySQL
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    # ChromaDB
    try:
        from app.rag.vector_store import get_vector_store
        vs = get_vector_store()
        vs._collection.count()
        checks["vector_store"] = "ok"
    except Exception as exc:
        checks["vector_store"] = f"error: {exc}"

    # Redis
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.redis_url)
        r.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {
        "status": overall,
        "version": "0.2.0",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/metrics", tags=["system"])
async def metrics():
    """인메모리 API 메트릭 — 경로별 호출 횟수 및 평균 응답 시간."""
    from app.core.middleware import get_metrics_stats
    return {"circuits": get_all_statuses(), "api": get_metrics_stats()}


@app.get("/admin/llm-cost", tags=["admin"])
async def llm_cost():
    """모듈별 LLM 토큰 사용량 및 비용 대시보드 (SYS-F72)."""
    from app.core.cost_monitor import get_total_cost, get_usage_summary
    return {
        "summary": get_usage_summary(),
        "total_cost_usd": round(get_total_cost(), 4),
        "budget_usd": settings.monthly_llm_budget_usd,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
