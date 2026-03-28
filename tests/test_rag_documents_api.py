"""RAG 문서 관리 API 통합 테스트 (TDD)"""

import io
from unittest.mock import MagicMock, patch

import pytest


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _pdf_bytes():
    return b"%PDF-1.4 fake pdf content for testing"


# ── POST /api/v1/documents ────────────────────────────────────

class TestUploadDocument:

    def test_requires_auth(self, client):
        resp = client.post("/api/v1/documents", files={"file": ("test.pdf", _pdf_bytes(), "application/pdf")})
        assert resp.status_code in (401, 403)

    def test_upload_pdf_returns_201(self, client, staff_token):
        with patch("app.api.routes.documents.ingest_documents", return_value={"chunk_count": 5, "elapsed_ms": 100}):
            with patch("app.api.routes.documents._save_upload_file", return_value="/tmp/test.pdf"):
                resp = client.post(
                    "/api/v1/documents",
                    files={"file": ("checkin.pdf", _pdf_bytes(), "application/pdf")},
                    data={"title": "체크인 SOP", "department_id": "1"},
                    headers=_auth(staff_token),
                )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["title"] == "체크인 SOP"
        assert data["chunk_count"] == 5

    def test_upload_docx_accepted(self, client, staff_token):
        with patch("app.api.routes.documents.ingest_documents", return_value={"chunk_count": 3, "elapsed_ms": 80}):
            with patch("app.api.routes.documents._save_upload_file", return_value="/tmp/test.docx"):
                resp = client.post(
                    "/api/v1/documents",
                    files={"file": ("manual.docx", b"fake docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                    data={"title": "운영 매뉴얼"},
                    headers=_auth(staff_token),
                )
        assert resp.status_code == 201

    def test_unsupported_format_returns_400(self, client, staff_token):
        resp = client.post(
            "/api/v1/documents",
            files={"file": ("test.xlsx", b"fake xlsx", "application/vnd.ms-excel")},
            data={"title": "엑셀파일"},
            headers=_auth(staff_token),
        )
        assert resp.status_code == 400

    def test_response_includes_elapsed_ms(self, client, staff_token):
        with patch("app.api.routes.documents.ingest_documents", return_value={"chunk_count": 2, "elapsed_ms": 250}):
            with patch("app.api.routes.documents._save_upload_file", return_value="/tmp/t.pdf"):
                resp = client.post(
                    "/api/v1/documents",
                    files={"file": ("t.pdf", _pdf_bytes(), "application/pdf")},
                    data={"title": "테스트"},
                    headers=_auth(staff_token),
                )
        assert resp.json().get("elapsed_ms") is not None


# ── GET /api/v1/documents ─────────────────────────────────────

class TestListDocuments:

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/documents")
        assert resp.status_code in (401, 403)

    def test_returns_list(self, client, staff_token):
        resp = client.get("/api/v1/documents", headers=_auth(staff_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_filter_by_department(self, client, staff_token, db, staff_user, test_dept):
        from app.database.models import Document as DocModel
        doc = DocModel(
            title="부서 문서",
            file_type="pdf",
            storage_key="dept/doc1.pdf",
            department_id=test_dept.id,
            uploaded_by=staff_user.id,
        )
        db.add(doc)
        db.commit()

        resp = client.get(
            f"/api/v1/documents?department_id={test_dept.id}",
            headers=_auth(staff_token),
        )
        assert resp.status_code == 200
        docs = resp.json()
        assert any(d["department_id"] == test_dept.id for d in docs)


# ── GET /api/v1/documents/{id} ────────────────────────────────

class TestGetDocument:

    def test_returns_document(self, client, staff_token, db, staff_user, test_dept):
        from app.database.models import Document as DocModel
        doc = DocModel(
            title="특정 문서",
            file_type="txt",
            storage_key="test/doc.txt",
            department_id=test_dept.id,
            uploaded_by=staff_user.id,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        resp = client.get(f"/api/v1/documents/{doc.id}", headers=_auth(staff_token))
        assert resp.status_code == 200
        assert resp.json()["title"] == "특정 문서"

    def test_404_for_unknown_id(self, client, staff_token):
        resp = client.get("/api/v1/documents/999999", headers=_auth(staff_token))
        assert resp.status_code == 404


# ── DELETE /api/v1/documents/{id} ────────────────────────────

class TestDeleteDocument:

    def test_staff_can_soft_delete(self, client, staff_token, db, staff_user, test_dept):
        from app.database.models import Document as DocModel
        doc = DocModel(
            title="삭제할 문서",
            file_type="pdf",
            storage_key="del/doc.pdf",
            department_id=test_dept.id,
            uploaded_by=staff_user.id,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        with patch("app.api.routes.documents.delete_document_chunks", return_value=0):
            resp = client.delete(f"/api/v1/documents/{doc.id}", headers=_auth(staff_token))

        assert resp.status_code == 204

    def test_404_for_unknown_id(self, client, staff_token):
        with patch("app.api.routes.documents.delete_document_chunks", return_value=0):
            resp = client.delete("/api/v1/documents/999999", headers=_auth(staff_token))
        assert resp.status_code == 404


# ── POST /api/v1/documents/{id}/versions ─────────────────────

class TestDocumentNewVersion:

    def test_creates_new_version(self, client, manager_token, db, manager_user, test_dept):
        from app.database.models import Document as DocModel
        doc = DocModel(
            title="버전 관리 문서",
            file_type="pdf",
            storage_key="ver/doc_v1.pdf",
            department_id=test_dept.id,
            uploaded_by=manager_user.id,
            version=1,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        with patch("app.api.routes.documents.ingest_documents", return_value={"chunk_count": 4, "elapsed_ms": 90}):
            with patch("app.api.routes.documents.delete_document_chunks", return_value=2):
                with patch("app.api.routes.documents._save_upload_file", return_value="/tmp/v2.pdf"):
                    resp = client.post(
                        f"/api/v1/documents/{doc.id}/versions",
                        files={"file": ("doc_v2.pdf", _pdf_bytes(), "application/pdf")},
                        headers=_auth(manager_token),
                    )

        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] >= 2

    def test_staff_cannot_update_version(self, client, staff_token, db, staff_user, test_dept):
        from app.database.models import Document as DocModel
        doc = DocModel(
            title="버전 문서",
            file_type="pdf",
            storage_key="ver/s_doc.pdf",
            department_id=test_dept.id,
            uploaded_by=staff_user.id,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        resp = client.post(
            f"/api/v1/documents/{doc.id}/versions",
            files={"file": ("new.pdf", _pdf_bytes(), "application/pdf")},
            headers=_auth(staff_token),
        )
        assert resp.status_code == 403
