"""Circuit Breaker 단위 테스트"""

import pytest

from app.core.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


def _failing():
    raise ValueError("fail")


def _ok():
    return "ok"


class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(name="test2", failure_threshold=3)
        for _ in range(3):
            with pytest.raises(ValueError):
                cb.call(_failing)
        assert cb.state == CircuitState.OPEN

    def test_open_blocks_calls(self):
        cb = CircuitBreaker(name="test3", failure_threshold=1)
        with pytest.raises(ValueError):
            cb.call(_failing)
        with pytest.raises(CircuitOpenError):
            cb.call(_ok)

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(name="test4", failure_threshold=3)
        with pytest.raises(ValueError):
            cb.call(_failing)
        cb.call(_ok)
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED
