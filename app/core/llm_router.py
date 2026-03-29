"""LLM 라우터 — 작업 Tier에 따라 로컬/클라우드 모델 자동 선택 (SYS-F70)"""

import logging
import socket
from enum import IntEnum
from urllib.parse import urlparse

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def _is_ollama_reachable(endpoint: str, timeout: float = 1.0) -> bool:
    """Ollama 엔드포인트 TCP 연결 가능 여부를 빠르게 확인."""
    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname or "localhost"
        port = parsed.port or 11434
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class TaskTier(IntEnum):
    """
    Tier 1: 로컬 전용  — OCR, 분류, 임베딩 (SYS-F70)
    Tier 2: 로컬 우선  — 구조 추출, 단순 RAG; 신뢰도 미달 시 클라우드 폴백 (SYS-F71)
    Tier 3: 클라우드   — 복합 추론, 멀티소스 RAG (SYS-F72)
    """

    LOCAL_ONLY = 1
    LOCAL_FIRST = 2
    CLOUD_FIRST = 3


class LLMRouter:
    """Tier 기반 로컬/클라우드 LLM 라우터.

    - Tier 1/2 → 로컬 Ollama 모델 우선
    - Tier 3    → 클라우드 OpenAI 모델
    - Tier 2    → confidence < threshold 시 클라우드 폴백 제공
    """

    def __init__(self) -> None:
        from app.core.config import settings

        self.threshold: float = settings.local_llm_confidence_threshold
        self._settings = settings
        self.__local: BaseChatModel | None = None
        self.__cloud: BaseChatModel | None = None

        # 시작 시 Ollama 연결 가능 여부 확인 — 불가능하면 LOCAL_FIRST를 CLOUD_FIRST로 업그레이드
        self._ollama_available: bool = _is_ollama_reachable(settings.local_llm_endpoint)
        if not self._ollama_available:
            logger.info(
                "Ollama 연결 불가 (%s) — LOCAL_FIRST 요청은 CLOUD_FIRST로 자동 업그레이드됩니다.",
                settings.local_llm_endpoint,
            )

    # lazy init — import 시점에 langchain_community 없어도 에러 안 남
    @property
    def _local(self) -> BaseChatModel:
        if self.__local is None:
            from langchain_community.chat_models import ChatOllama

            self.__local = ChatOllama(
                model=self._settings.local_llm_model,
                base_url=self._settings.local_llm_endpoint,
                temperature=0,
            )
        return self.__local

    @property
    def _cloud(self) -> BaseChatModel:
        if self.__cloud is None:
            from langchain_openai import ChatOpenAI

            self.__cloud = ChatOpenAI(
                model=self._settings.llm_model,
                api_key=self._settings.openai_api_key,
                temperature=0,
            )
        return self.__cloud

    def get_llm(self, tier: TaskTier) -> BaseChatModel:
        """Tier에 따른 기본 LLM 반환."""
        if tier == TaskTier.CLOUD_FIRST:
            logger.debug("LLMRouter: Tier 3 → 클라우드 LLM 선택")
            return self._cloud
        logger.debug("LLMRouter: Tier %d → 로컬 LLM 선택", int(tier))
        return self._local

    def get_fallback(self, tier: TaskTier) -> BaseChatModel | None:
        """Tier 2 전용 폴백 LLM 반환. Tier 1은 None."""
        if tier == TaskTier.LOCAL_FIRST:
            return self._cloud
        return None

    def should_fallback(self, confidence: float) -> bool:
        """confidence가 임계값 미만이면 클라우드 폴백 필요."""
        return confidence < self.threshold

    def safe_invoke(
        self,
        tier: "TaskTier",
        messages,
        module: str = "llm",
        **kwargs,
    ):
        """CircuitBreaker + 폴백을 통합한 안전한 LLM 호출 (SYS-F41).

        - Tier 1: 로컬 모델 직접 호출 (CircuitBreaker 없음)
        - Tier 2: 로컬 우선, 실패 시 클라우드 폴백 (is_fallback=True 기록)
        - Tier 3: CircuitBreaker로 보호된 클라우드 호출
        """
        from app.core.circuit_breaker import get_circuit_breaker
        from app.core.cost_monitor import record_usage

        def _extract_usage(result) -> tuple[int, int]:
            meta = getattr(result, "usage_metadata", None) or {}
            return meta.get("input_tokens", 0), meta.get("output_tokens", 0)

        if tier == TaskTier.LOCAL_ONLY:
            result = self._local.invoke(messages, **kwargs)
            prompt_t, comp_t = _extract_usage(result)
            if prompt_t or comp_t:
                record_usage(module, prompt_t, comp_t, model="local", is_fallback=False)
            return result

        if tier == TaskTier.LOCAL_FIRST:
            # Ollama 미실행 시 연결 시도 없이 즉시 클라우드로
            if not self._ollama_available:
                breaker = get_circuit_breaker("openai")
                result = breaker.call(self._cloud.invoke, messages, **kwargs)
                prompt_t, comp_t = _extract_usage(result)
                record_usage(module, prompt_t, comp_t, model=self._settings.llm_model, is_fallback=True)
                return result

            try:
                result = self._local.invoke(messages, **kwargs)
                prompt_t, comp_t = _extract_usage(result)
                if prompt_t or comp_t:
                    record_usage(module, prompt_t, comp_t, model="local", is_fallback=False)
                return result
            except Exception as local_exc:
                logger.warning("로컬 LLM 실패, 클라우드 폴백: %s", local_exc)
                self._ollama_available = False  # 이후 요청은 즉시 클라우드로

            # 클라우드 폴백
            breaker = get_circuit_breaker("openai")
            result = breaker.call(self._cloud.invoke, messages, **kwargs)
            prompt_t, comp_t = _extract_usage(result)
            record_usage(module, prompt_t, comp_t, model=self._settings.llm_model, is_fallback=True)
            return result

        # Tier 3: CLOUD_FIRST — CircuitBreaker 보호
        breaker = get_circuit_breaker("openai")
        result = breaker.call(self._cloud.invoke, messages, **kwargs)
        prompt_t, comp_t = _extract_usage(result)
        record_usage(module, prompt_t, comp_t, model=self._settings.llm_model, is_fallback=False)
        return result


# 싱글톤
llm_router = LLMRouter()
