"""Circuit Breaker — 외부 API 장애 격리"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"        # 정상
    OPEN = "open"            # 차단 중
    HALF_OPEN = "half_open"  # 회복 시도


class CircuitOpenError(Exception):
    """Circuit이 OPEN 상태일 때 호출 차단."""


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5    # 연속 실패 N회 시 OPEN
    recovery_timeout: int = 60    # OPEN 유지 시간 (초)
    success_threshold: int = 2    # HALF_OPEN에서 성공 N회 시 CLOSED

    state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    failure_count: int = field(default=0, init=False)
    success_count: int = field(default=0, init=False)
    last_failure_time: float = field(default=0.0, init=False)

    def call(self, func, *args, **kwargs):
        if self.state == CircuitState.OPEN:
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                logger.info(f"Circuit [{self.name}] HALF_OPEN — 회복 시도")
            else:
                raise CircuitOpenError(
                    f"Circuit [{self.name}] OPEN. {self.recovery_timeout - elapsed:.0f}초 후 재시도"
                )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except CircuitOpenError:
            raise
        except Exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                logger.info(f"Circuit [{self.name}] CLOSED — 복구 완료")
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0

    def _on_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                f"Circuit [{self.name}] OPEN — {self.failure_threshold}회 연속 실패"
            )

    @property
    def status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
        }


# 싱글톤 레지스트리
_registry: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str, **kwargs) -> CircuitBreaker:
    if name not in _registry:
        _registry[name] = CircuitBreaker(name=name, **kwargs)
    return _registry[name]


def with_circuit_breaker(breaker_name: str, **breaker_kwargs):
    """동기 함수용 데코레이터."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            breaker = get_circuit_breaker(breaker_name, **breaker_kwargs)
            return breaker.call(func, *args, **kwargs)

        return wrapper

    return decorator


def get_all_statuses() -> list[dict]:
    return [cb.status for cb in _registry.values()]
