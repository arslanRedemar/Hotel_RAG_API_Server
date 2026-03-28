"""RAG 인제스트 모듈 단위 테스트 (TDD)"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from langchain_core.documents import Document


# ── 헬퍼 ─────────────────────────────────────────────────────

def _make_mock_vectorstore():
    vs = MagicMock()
    vs.add_documents.return_value = ["id1", "id2"]
    return vs


def _make_mock_embeddings():
    return MagicMock()


# ── ingest_documents ─────────────────────────────────────────

class TestIngestDocuments:

    def test_raises_if_dir_not_found(self, tmp_path):
        from app.rag.ingest import ingest_documents
        with pytest.raises(FileNotFoundError):
            ingest_documents(str(tmp_path / "nonexistent"))

    def test_raises_if_no_documents(self, tmp_path):
        from app.rag.ingest import ingest_documents
        with patch("app.rag.ingest.get_vector_store", return_value=_make_mock_vectorstore()):
            with patch("app.rag.ingest.get_embeddings", return_value=_make_mock_embeddings()):
                with pytest.raises(ValueError, match="인제스트할 문서"):
                    ingest_documents(str(tmp_path))

    def test_loads_txt_file(self, tmp_path):
        from app.rag.ingest import ingest_documents
        (tmp_path / "test.txt").write_text("호텔 체크인 절차", encoding="utf-8")
        mock_vs = _make_mock_vectorstore()

        with patch("app.rag.ingest.get_vector_store", return_value=mock_vs):
            with patch("app.rag.ingest.get_embeddings", return_value=_make_mock_embeddings()):
                result = ingest_documents(str(tmp_path))

        assert isinstance(result, dict)
        assert result["chunk_count"] > 0

    def test_returns_timing_info(self, tmp_path):
        from app.rag.ingest import ingest_documents
        (tmp_path / "test.txt").write_text("내용" * 100, encoding="utf-8")
        mock_vs = _make_mock_vectorstore()

        with patch("app.rag.ingest.get_vector_store", return_value=mock_vs):
            with patch("app.rag.ingest.get_embeddings", return_value=_make_mock_embeddings()):
                result = ingest_documents(str(tmp_path))

        assert "elapsed_ms" in result
        assert result["elapsed_ms"] >= 0

    def test_loads_docx_file(self, tmp_path):
        from app.rag.ingest import ingest_documents
        docx_path = tmp_path / "sop.docx"
        docx_path.write_bytes(b"fake docx content")  # 실제 파싱은 모킹

        mock_vs = _make_mock_vectorstore()
        mock_doc = Document(page_content="DOCX 내용", metadata={"source": str(docx_path)})

        with patch("app.rag.ingest.get_vector_store", return_value=mock_vs):
            with patch("app.rag.ingest.get_embeddings", return_value=_make_mock_embeddings()):
                with patch("app.rag.ingest.Docx2txtLoader") as MockLoader:
                    MockLoader.return_value.load.return_value = [mock_doc]
                    result = ingest_documents(str(tmp_path))

        assert result["chunk_count"] > 0

    def test_metadata_includes_department(self, tmp_path):
        from app.rag.ingest import ingest_documents
        (tmp_path / "test.txt").write_text("내용", encoding="utf-8")
        mock_vs = _make_mock_vectorstore()
        added_chunks = []

        def capture_add(docs, **kwargs):
            added_chunks.extend(docs)
            return ["id1"] * len(docs)

        mock_vs.add_documents.side_effect = capture_add

        with patch("app.rag.ingest.get_vector_store", return_value=mock_vs):
            with patch("app.rag.ingest.get_embeddings", return_value=_make_mock_embeddings()):
                ingest_documents(str(tmp_path), department_id=3, uploaded_by=1, version="2.0")

        assert len(added_chunks) > 0
        meta = added_chunks[0].metadata
        assert meta.get("department_id") == "3"
        assert meta.get("uploaded_by") == "1"
        assert meta.get("version") == "2.0"

    def test_uses_embedding_router(self, tmp_path):
        """get_vector_store 를 통해 embedding_router 가 사용되는지 확인 (RAG-F16)"""
        from app.rag.ingest import ingest_documents
        (tmp_path / "test.txt").write_text("내용", encoding="utf-8")
        mock_vs = _make_mock_vectorstore()

        with patch("app.rag.ingest.get_vector_store", return_value=mock_vs) as mock_vs_fn:
            with patch("app.rag.ingest.get_embeddings", return_value=_make_mock_embeddings()):
                ingest_documents(str(tmp_path))

        # get_vector_store가 호출되어야 함 (내부에서 embedding_router 사용)
        mock_vs_fn.assert_called_once()


# ── ingest_sop_to_vector_store ─────────────────────────────

class TestIngestSOPToVectorStore:

    def _make_sop(self):
        sop = MagicMock()
        sop.id = "sop-001"
        sop.title = "체크인 SOP"
        sop.department_id = 1
        sop.version = "1.0"
        sop.steps = [{"step_no": 1, "action": "고객 맞이", "responsible": "프런트", "notes": None}]
        sop.checklist_items = [{"text": "신분증 확인", "required": True}]
        sop.cautions = ["주의: 개인정보 보호"]
        return sop

    def test_returns_chunk_ids(self):
        from app.rag.ingest import ingest_sop_to_vector_store
        mock_vs = _make_mock_vectorstore()

        with patch("app.rag.ingest.get_vector_store", return_value=mock_vs):
            with patch("app.rag.ingest.get_embeddings", return_value=_make_mock_embeddings()):
                ids = ingest_sop_to_vector_store(self._make_sop())

        assert isinstance(ids, list)
        assert len(ids) > 0

    def test_metadata_includes_sop_fields(self):
        from app.rag.ingest import ingest_sop_to_vector_store
        mock_vs = _make_mock_vectorstore()
        added_docs = []

        def capture(docs, **kwargs):
            added_docs.extend(docs)
            return ["id1"] * len(docs)

        mock_vs.add_documents.side_effect = capture

        with patch("app.rag.ingest.get_vector_store", return_value=mock_vs):
            with patch("app.rag.ingest.get_embeddings", return_value=_make_mock_embeddings()):
                ingest_sop_to_vector_store(self._make_sop())

        meta = added_docs[0].metadata
        assert meta["source_id"] == "sop-001"
        assert meta["doc_type"] == "sop"
        assert meta["version"] == "1.0"

    def test_content_includes_steps_and_checklist(self):
        from app.rag.ingest import ingest_sop_to_vector_store
        mock_vs = _make_mock_vectorstore()
        added_docs = []

        mock_vs.add_documents.side_effect = lambda docs, **kw: (added_docs.extend(docs), ["id1"])[1]

        with patch("app.rag.ingest.get_vector_store", return_value=mock_vs):
            with patch("app.rag.ingest.get_embeddings", return_value=_make_mock_embeddings()):
                ingest_sop_to_vector_store(self._make_sop())

        all_content = " ".join(d.page_content for d in added_docs)
        assert "고객 맞이" in all_content
        assert "신분증 확인" in all_content


# ── delete_document_chunks ────────────────────────────────

class TestDeleteDocumentChunks:

    def test_deletes_by_source_id(self):
        from app.rag.ingest import delete_document_chunks
        mock_vs = _make_mock_vectorstore()
        mock_vs.get.return_value = {"ids": ["chunk1", "chunk2"]}
        mock_vs._collection.get.return_value = {"ids": ["chunk1", "chunk2"]}

        with patch("app.rag.ingest.get_vector_store", return_value=mock_vs):
            with patch("app.rag.ingest.get_embeddings", return_value=_make_mock_embeddings()):
                deleted = delete_document_chunks("doc-001")

        assert deleted >= 0

    def test_returns_zero_if_no_chunks(self):
        from app.rag.ingest import delete_document_chunks
        mock_vs = _make_mock_vectorstore()
        mock_vs._collection.get.return_value = {"ids": []}

        with patch("app.rag.ingest.get_vector_store", return_value=mock_vs):
            with patch("app.rag.ingest.get_embeddings", return_value=_make_mock_embeddings()):
                deleted = delete_document_chunks("nonexistent-id")

        assert deleted == 0
