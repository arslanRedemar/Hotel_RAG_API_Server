"""RAG 채팅 API 통합 테스트 (TDD)"""

from unittest.mock import patch


from app.rag.graph import SourceDetail


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_source_detail(source="sop.pdf", page=1, section=None, preview="내용"):
    return SourceDetail(source=source, page=page, section=section, chunk_preview=preview)


# ── POST /api/v1/chat ─────────────────────────────────────────

class TestChatEndpoint:

    def test_requires_auth(self, client):
        resp = client.post("/api/v1/chat", json={"message": "안녕"})
        assert resp.status_code in (401, 403)

    def test_returns_answer_with_auth(self, client, staff_token):
        src = _make_source_detail("sop.pdf", page=1)
        with patch("app.api.routes.chat.rag_chat", return_value=("체크인은 14시입니다.", [src])):
            resp = client.post(
                "/api/v1/chat",
                json={"message": "체크인 시간은?"},
                headers=_auth(staff_token),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert data["answer"] == "체크인은 14시입니다."

    def test_response_includes_session_id(self, client, staff_token):
        with patch("app.api.routes.chat.rag_chat", return_value=("답변", [])):
            resp = client.post(
                "/api/v1/chat",
                json={"message": "안녕"},
                headers=_auth(staff_token),
            )
        assert resp.status_code == 200
        assert "session_id" in resp.json()
        assert resp.json()["session_id"] is not None

    def test_reuses_provided_session_id(self, client, staff_token):
        with patch("app.api.routes.chat.rag_chat", return_value=("답변", [])):
            resp = client.post(
                "/api/v1/chat",
                json={"message": "안녕", "session_id": "my-custom-session"},
                headers=_auth(staff_token),
            )
        assert resp.json()["session_id"] == "my-custom-session"

    def test_response_includes_sources(self, client, staff_token):
        src = _make_source_detail("checkin.pdf", page=1)
        with patch("app.api.routes.chat.rag_chat", return_value=("답변", [src])):
            resp = client.post(
                "/api/v1/chat",
                json={"message": "체크인?"},
                headers=_auth(staff_token),
            )
        data = resp.json()
        assert "sources" in data or "source_documents" in data

    def test_response_includes_source_documents_detail(self, client, staff_token):
        src = SourceDetail(
            source="sop.pdf",
            page=3,
            section="2. 체크인",
            chunk_preview="체크인 절차 상세 내용입니다.",
        )
        with patch("app.api.routes.chat.rag_chat", return_value=("답변", [src])):
            resp = client.post(
                "/api/v1/chat",
                json={"message": "절차?"},
                headers=_auth(staff_token),
            )
        data = resp.json()
        assert "source_documents" in data
        if data["source_documents"]:
            src_data = data["source_documents"][0]
            assert "source" in src_data
            assert "chunk_preview" in src_data

    def test_message_saved_to_db(self, client, staff_token, db):
        from app.database.models import ChatMessage
        with patch("app.api.routes.chat.rag_chat", return_value=("DB 저장 테스트", [])):
            resp = client.post(
                "/api/v1/chat",
                json={"message": "저장 테스트 메시지", "session_id": "save-test-session"},
                headers=_auth(staff_token),
            )
        assert resp.status_code == 200
        msgs = db.query(ChatMessage).filter_by(session_id="save-test-session").all()
        assert len(msgs) >= 2  # human + ai
        roles = {m.role for m in msgs}
        assert "human" in roles
        assert "ai" in roles

    def test_rag_error_returns_500(self, client, staff_token):
        with patch("app.api.routes.chat.rag_chat", side_effect=Exception("LLM 오류")):
            resp = client.post(
                "/api/v1/chat",
                json={"message": "오류 테스트"},
                headers=_auth(staff_token),
            )
        assert resp.status_code == 500

    def test_accepts_department_ids(self, client, staff_token):
        with patch("app.api.routes.chat.rag_chat", return_value=("답변", [])):
            resp = client.post(
                "/api/v1/chat",
                json={"message": "질문", "department_ids": [1, 2]},
                headers=_auth(staff_token),
            )
        assert resp.status_code == 200


# ── GET /api/v1/history/{session_id} ─────────────────────────

class TestHistoryEndpoint:

    def test_returns_messages(self, client, staff_token, db):
        from app.database.crud import save_message
        save_message(db, "hist-session-1", "human", "질문")
        save_message(db, "hist-session-1", "ai", "답변")

        resp = client.get("/api/v1/history/hist-session-1", headers=_auth(staff_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data
        assert len(data["messages"]) == 2

    def test_404_for_unknown_session(self, client, staff_token):
        resp = client.get("/api/v1/history/nonexistent-session-xyz", headers=_auth(staff_token))
        assert resp.status_code == 404

    def test_delete_history(self, client, staff_token, db):
        from app.database.crud import save_message
        save_message(db, "del-session-1", "human", "삭제할 메시지")

        resp = client.delete("/api/v1/history/del-session-1", headers=_auth(staff_token))
        assert resp.status_code == 204
