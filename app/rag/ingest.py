import os
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.rag.vector_store import get_vector_store


def ingest_documents(docs_dir: str = "./data/docs", collection_name: str = "hotel_docs") -> int:
    """data/docs 디렉토리의 문서를 벡터 DB에 인제스트합니다."""
    docs_path = Path(docs_dir)
    if not docs_path.exists():
        raise FileNotFoundError(f"문서 디렉토리를 찾을 수 없습니다: {docs_dir}")

    documents = []

    # PDF 로딩
    for pdf_file in docs_path.glob("**/*.pdf"):
        loader = PyPDFLoader(str(pdf_file))
        documents.extend(loader.load())

    # TXT 로딩
    for txt_file in docs_path.glob("**/*.txt"):
        loader = TextLoader(str(txt_file), encoding="utf-8")
        documents.extend(loader.load())

    if not documents:
        raise ValueError("인제스트할 문서가 없습니다. data/docs/ 디렉토리에 PDF 또는 TXT 파일을 추가해주세요.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    chunks = splitter.split_documents(documents)

    vector_store = get_vector_store(collection_name)
    vector_store.add_documents(chunks)

    return len(chunks)
