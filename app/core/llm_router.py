"""LLM 라우터 — 작업 Tier에 따라 로컬/클라우드 모델 자동 선택 (SYS-F70)"""

import logging
from enum import IntEnum

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


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


# 싱글톤
llm_router = LLMRouter()
