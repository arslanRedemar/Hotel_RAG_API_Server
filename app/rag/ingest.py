import os
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.rag.vector_store import get_vector_store


def ingest_sop_to_vector_store(sop, collection_name: str = "hotel_docs") -> list[str]:
    """확정된 SOP를 구조화 텍스트로 직렬화 후 벡터 DB에 인덱싱.

    Returns:
        추가된 청크 ID 목록
    """
    text_parts = [f"# {sop.title}\n"]

    for step in sop.steps or []:
        line = f"Step {step.get('step_no', '?')}: {step.get('action', '')}"
        if step.get("responsible"):
            line += f" (담당: {step['responsible']})"
        if step.get("notes"):
            line += f" - {step['notes']}"
        text_parts.append(line)

    for item in sop.checklist_items or []:
        text_parts.append(f"체크: {item.get('text', '')}")

    for caution in sop.cautions or []:
        text_parts.append(f"주의: {caution}")

    doc = Document(
        page_content="\n".join(text_parts),
        metadata={
            "source": f"sop/{sop.id}",
            "source_id": sop.id,
            "title": sop.title,
            "department": str(sop.department_id or ""),
            "version": sop.version,
            "doc_type": "sop",
        },
    )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    chunks = splitter.split_documents([doc])

    vector_store = get_vector_store(collection_name)
    ids = vector_store.add_documents(chunks)
    return ids


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
