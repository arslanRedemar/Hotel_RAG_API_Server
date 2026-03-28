"""구조화된 JSON 로깅 (Docker 컨테이너 로그 수집 최적화)"""

import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """JSON Lines 형태 구조화 로그."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        for field in ("request_id", "user_id", "duration_ms", "status_code", "path", "method"):
            if hasattr(record, field):
                log_data[field] = getattr(record, field)

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    """애플리케이션 로깅 초기화 — main.py lifespan에서 호출."""
    root = logging.getLogger()
    root.setLevel(level)

    # 기존 핸들러 제거 (중복 방지)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)

    # 외부 라이브러리 로그 레벨 억제
    for noisy in ("httpx", "sqlalchemy.engine", "chromadb", "urllib3", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
