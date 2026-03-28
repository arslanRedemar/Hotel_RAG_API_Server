"""벡터 저장소 — embedding_router 기반 (RAG-F16)"""

from langchain_chroma import Chroma
from app.core.config import settings


def get_vector_store(collection_name: str = "hotel_docs") -> Chroma:
    """RAG-F16: embedding_router를 통해 임베딩 프로바이더 결정"""
    from app.core.embedding_router import get_embeddings
    embeddings = get_embeddings()
    return Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=settings.chroma_persist_dir,
    )
