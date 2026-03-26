from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from app.core.config import settings


def get_vector_store(collection_name: str = "hotel_docs") -> Chroma:
    embeddings = OpenAIEmbeddings(
        model=settings.embedding_model,
        openai_api_key=settings.openai_api_key,
    )
    return Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=settings.chroma_persist_dir,
    )
