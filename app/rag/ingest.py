"""RAG 문서 인제스트 파이프라인 — DOCX 지원, 메타데이터 강화, 임베딩 라우터 (RAG-F01/02/16)"""

import time
import logging
from datetime import datetime, timezone
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.document_loaders import Docx2txtLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.core.embedding_router import get_embeddings
from app.rag.vector_store import get_vector_store

logger = logging.getLogger(__name__)


def ingest_sop_to_vector_store(
    sop,
    collection_name: str = "hotel_docs",
) -> list[str]:
    """확정된 SOP를 구조화 텍스트로 직렬화 후 벡터 DB에 인덱싱 (RAG-F02 메타데이터 강화)"""
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
            "department_id": str(sop.department_id or ""),
            "version": sop.version,
            "doc_type": "sop",
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
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


def ingest_documents(
    docs_dir: str = "./data/docs",
    collection_name: str = "hotel_docs",
    department_id: int | None = None,
    uploaded_by: int | None = None,
    version: str = "1.0",
) -> dict:
    """data/docs 디렉토리의 문서를 벡터 DB에 인제스트합니다.

    RAG-F01: PDF / TXT / DOCX 지원
    RAG-F02: 부서/버전/업로더 메타데이터 저장
    RAG-F04: 인덱싱 소요 시간 반환
    RAG-F16: embedding_router 사용

    Returns:
        {"chunk_count": int, "elapsed_ms": int}
    """
    start = time.perf_counter()
    docs_path = Path(docs_dir)
    if not docs_path.exists():
        raise FileNotFoundError(f"문서 디렉토리를 찾을 수 없습니다: {docs_dir}")

    documents: list[Document] = []

    # PDF 로딩
    for pdf_file in docs_path.glob("**/*.pdf"):
        loader = PyPDFLoader(str(pdf_file))
        docs = loader.load()
        for i, doc in enumerate(docs):
            doc.metadata.setdefault("source", pdf_file.name)
            doc.metadata["chunk_index"] = i
        documents.extend(docs)

    # TXT 로딩
    for txt_file in docs_path.glob("**/*.txt"):
        loader = TextLoader(str(txt_file), encoding="utf-8")
        docs = loader.load()
        for i, doc in enumerate(docs):
            doc.metadata.setdefault("source", txt_file.name)
            doc.metadata["chunk_index"] = i
        documents.extend(docs)

    # DOCX 로딩 (RAG-F01)
    for docx_file in docs_path.glob("**/*.docx"):
        loader = Docx2txtLoader(str(docx_file))
        docs = loader.load()
        for i, doc in enumerate(docs):
            doc.metadata.setdefault("source", docx_file.name)
            doc.metadata["chunk_index"] = i
        documents.extend(docs)

    if not documents:
        raise ValueError(
            "인제스트할 문서가 없습니다. "
            "data/docs/ 디렉토리에 PDF, TXT, 또는 DOCX 파일을 추가해주세요."
        )

    # RAG-F02: 공통 메타데이터 주입
    uploaded_at = datetime.now(timezone.utc).isoformat()
    for doc in documents:
        if department_id is not None:
            doc.metadata["department_id"] = str(department_id)
        if uploaded_by is not None:
            doc.metadata["uploaded_by"] = str(uploaded_by)
        doc.metadata["version"] = version
        doc.metadata["uploaded_at"] = uploaded_at

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    chunks = splitter.split_documents(documents)

    vector_store = get_vector_store(collection_name)
    vector_store.add_documents(chunks)

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info("인제스트 완료: %d 청크, %d ms", len(chunks), elapsed_ms)

    return {"chunk_count": len(chunks), "elapsed_ms": elapsed_ms}


def delete_document_chunks(
    source_id: str,
    collection_name: str = "hotel_docs",
) -> int:
    """특정 source_id의 모든 청크를 벡터 DB에서 삭제 (RAG-F03 버전 교체 지원)

    Returns:
        삭제된 청크 수
    """
    vector_store = get_vector_store(collection_name)
    try:
        result = vector_store._collection.get(
            where={"source_id": source_id}
        )
        ids = result.get("ids", [])
        if ids:
            vector_store._collection.delete(ids=ids)
            logger.info("청크 삭제 완료 source_id=%s count=%d", source_id, len(ids))
        return len(ids)
    except Exception as exc:
        logger.warning("청크 삭제 실패 source_id=%s: %s", source_id, exc)
        return 0
