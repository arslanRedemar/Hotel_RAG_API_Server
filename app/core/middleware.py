"""HTTP 요청/응답 로깅 및 메트릭 미들웨어"""

import logging
import time
import uuid
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("app.middleware")

# 클래스 수준 공유 통계 (인스턴스 참조 없이 /metrics에서 접근 가능)
_stats_count: dict[str, int] = defaultdict(int)
_stats_total_ms: dict[str, float] = defaultdict(float)
_stats_errors: dict[str, int] = defaultdict(int)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """모든 HTTP 요청/응답을 구조화된 로그로 기록."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = uuid.uuid4().hex[:8]
        request.state.request_id = request_id

        start = time.perf_counter()

        logger.info(
            "요청 시작",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host if request.client else "unknown",
            },
        )

        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)

        log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            log_level,
            "요청 완료",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )

        response.headers["X-Request-ID"] = request_id
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """인메모리 API 메트릭 수집."""

    async def dispatch(self, request: Request, call_next) -> Response:
        key = f"{request.method}:{request.url.path}"
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start) * 1000
        _stats_count[key] += 1
        _stats_total_ms[key] += duration_ms
        if response.status_code >= 400:
            _stats_errors[key] += 1

        return response


def get_metrics_stats() -> dict:
    stats = {}
    for key, count in _stats_count.items():
        avg = _stats_total_ms[key] / count if count else 0
        stats[key] = {
            "count": count,
            "avg_ms": round(avg, 2),
            "errors": _stats_errors.get(key, 0),
        }
    return stats
