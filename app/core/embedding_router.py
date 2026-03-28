"""임베딩 프로바이더 라우터 — 환경변수로 로컬/클라우드 전환 (RAG-F16)"""

import logging

from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)


def get_embeddings() -> Embeddings:
    """EMBEDDING_PROVIDER 설정에 따라 임베딩 인스턴스 반환.

    - "local"  : Ollama nomic-embed-text (기본값, 무료)
    - "openai" : OpenAI text-embedding-3-small
    """
    from app.core.config import settings

    provider = settings.embedding_provider.lower()

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        logger.info("임베딩 프로바이더: OpenAI (%s)", settings.embedding_model)
        return OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.openai_api_key,
        )

    # 기본값: 로컬 Ollama
    from langchain_community.embeddings import OllamaEmbeddings

    logger.info(
        "임베딩 프로바이더: Ollama 로컬 (%s @ %s)",
        settings.local_embedding_model,
        settings.local_llm_endpoint,
    )
    return OllamaEmbeddings(
        model=settings.local_embedding_model,
        base_url=settings.local_llm_endpoint,
    )
