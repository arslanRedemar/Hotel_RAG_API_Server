"""세션 목록 API 테스트 (TDD — Phase 4 세션 이력 사이드바)"""

from app.database.models import ChatSession, ChatMessage


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestListSessions:
    """GET /api/v1/history/sessions — 세션 목록 (최신순)"""

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/history/sessions")
        assert resp.status_code in (401, 403)

    def test_returns_list(self, client, staff_token):
        resp = client.get("/api/v1/history/sessions", headers=_auth(staff_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_includes_session_id(self, client, staff_token, db):
        session = ChatSession(session_id="test-session-abc")
        db.add(session)
        db.add(ChatMessage(session_id="test-session-abc", role="human", content="안녕하세요"))
        db.commit()

        resp = client.get("/api/v1/history/sessions", headers=_auth(staff_token))
        assert resp.status_code == 200
        ids = [s["session_id"] for s in resp.json()]
        assert "test-session-abc" in ids

    def test_includes_latest_message_preview(self, client, staff_token, db):
        session = ChatSession(session_id="preview-session-xyz")
        db.add(session)
        db.add(ChatMessage(session_id="preview-session-xyz", role="human", content="호텔 체크인은 몇시인가요"))
        db.commit()

        resp = client.get("/api/v1/history/sessions", headers=_auth(staff_token))
        assert resp.status_code == 200
        entry = next((s for s in resp.json() if s["session_id"] == "preview-session-xyz"), None)
        assert entry is not None
        assert "preview" in entry or "latest_message" in entry or "last_message" in entry

    def test_limit_parameter(self, client, staff_token, db):
        for i in range(5):
            s = ChatSession(session_id=f"limit-test-{i}")
            db.add(s)
            db.add(ChatMessage(session_id=f"limit-test-{i}", role="human", content=f"메시지 {i}"))
        db.commit()

        resp = client.get("/api/v1/history/sessions?limit=3", headers=_auth(staff_token))
        assert resp.status_code == 200
        assert len(resp.json()) <= 3
