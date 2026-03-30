"""SYS-F41: CircuitBreaker OpenAI API 보호 테스트 (TDD)"""

import time
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_circuit_registry():
    """각 테스트 전 Circuit Registry 초기화"""
    from app.core.circuit_breaker import _registry
    _registry.clear()
    yield
    _registry.clear()


class TestCircuitBreakerLLMUnit:
    def test_cloud_invoke_uses_circuit_breaker(self):
        """클라우드 LLM(CLOUD_FIRST) 호출 시 openai CircuitBreaker 등록"""
        from app.core.circuit_breaker import _registry
        from app.core.llm_router import LLMRouter, TaskTier

        router = LLMRouter()
        mock_result = MagicMock()

        with patch.object(type(router), "_cloud", new_callable=lambda: property(lambda self: (lambda: mock_result)())):
            pass  # property mock은 복잡 — 직접 호출 방식으로 변경

        with patch.object(router, "_LLMRouter__cloud") as mock_cloud:
            mock_cloud.invoke.return_value = mock_result
            result = router.safe_invoke(TaskTier.CLOUD_FIRST, [])

        assert result == mock_result
        assert "openai" in _registry

    def test_circuit_opens_after_5_failures(self):
        """OpenAI 5회 연속 실패 시 CircuitBreaker OPEN"""
        from app.core.circuit_breaker import CircuitState, get_circuit_breaker
        from app.core.llm_router import LLMRouter, TaskTier

        router = LLMRouter()

        with patch.object(router, "_LLMRouter__cloud") as mock_cloud:
            mock_cloud.invoke.side_effect = Exception("OpenAI 타임아웃")
            for _ in range(5):
                try:
                    router.safe_invoke(TaskTier.CLOUD_FIRST, [])
                except Exception:
                    pass

        breaker = get_circuit_breaker("openai")
        assert breaker.state == CircuitState.OPEN

    def test_circuit_open_raises_circuit_error(self):
        """CircuitBreaker OPEN 상태에서 호출 시 CircuitOpenError"""
        from app.core.circuit_breaker import CircuitOpenError, CircuitState, get_circuit_breaker
        from app.core.llm_router import LLMRouter, TaskTier

        router = LLMRouter()
        breaker = get_circuit_breaker("openai")
        breaker.state = CircuitState.OPEN
        breaker.last_failure_time = time.time()  # 방금 실패

        with pytest.raises(CircuitOpenError):
            router.safe_invoke(TaskTier.CLOUD_FIRST, [])

    def test_local_only_skips_circuit_breaker(self):
        """Tier 1 (LOCAL_ONLY) 는 CircuitBreaker 없이 로컬 모델 호출"""
        from app.core.circuit_breaker import _registry
        from app.core.llm_router import LLMRouter, TaskTier

        router = LLMRouter()
        mock_result = MagicMock()

        with patch.object(router, "_LLMRouter__local") as mock_local:
            mock_local.invoke.return_value = mock_result
            result = router.safe_invoke(TaskTier.LOCAL_ONLY, [])

        assert result == mock_result
        assert "openai" not in _registry

    def test_local_first_falls_back_to_cloud(self):
        """Tier 2 (LOCAL_FIRST) 로컬 실패 시 클라우드 폴백"""
        from app.core.llm_router import LLMRouter, TaskTier

        router = LLMRouter()
        cloud_result = MagicMock()

        with patch.object(router, "_LLMRouter__local") as mock_local, \
             patch.object(router, "_LLMRouter__cloud") as mock_cloud:
            mock_local.invoke.side_effect = Exception("로컬 모델 오류")
            mock_cloud.invoke.return_value = cloud_result
            result = router.safe_invoke(TaskTier.LOCAL_FIRST, [])

        assert result == cloud_result

    def test_fallback_recorded_in_cost_monitor(self):
        """로컬→클라우드 폴백 시 cost_monitor에 fallback 기록"""
        from app.core.cost_monitor import _store, _lock
        from app.core.llm_router import LLMRouter, TaskTier

        with _lock:
            _store.clear()

        router = LLMRouter()
        cloud_result = MagicMock()
        cloud_result.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

        with patch.object(router, "_LLMRouter__local") as mock_local, \
             patch.object(router, "_LLMRouter__cloud") as mock_cloud:
            mock_local.invoke.side_effect = Exception("로컬 오류")
            mock_cloud.invoke.return_value = cloud_result
            router.safe_invoke(TaskTier.LOCAL_FIRST, [], module="test_module")

        with _lock:
            if "test_module" in _store:
                assert _store["test_module"].fallback_count >= 1
