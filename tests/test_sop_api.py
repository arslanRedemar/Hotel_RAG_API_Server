"""SOP API 엔드포인트 통합 테스트"""

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from app.database.models import SOP
from app.sop.service import SOPService


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_active_sop(db, user, dept, sop_id: str = "active-sop-1") -> SOP:
    sop = SOP(
        id=sop_id,
        title="확정된 SOP",
        department_id=dept.id,
        status="active",
        version="1.0",
        steps=[{"step_no": 1, "action": "고객 응대", "responsible": "프런트", "duration_min": 2, "notes": None}],
        checklist_items=[{"text": "신분증 확인", "required": True}],
        cautions=["주의사항"],
        review_required=False,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(sop)
    db.commit()
    db.refresh(sop)
    return sop


def _make_draft_sop(db, user, dept, sop_id: str = "draft-sop-1") -> SOP:
    sop = SOP(
        id=sop_id,
        title="초안 SOP",
        department_id=dept.id,
        status="draft",
        version="1.0",
        steps=[],
        checklist_items=[],
        cautions=[],
        review_required=True,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(sop)
    db.commit()
    db.refresh(sop)
    return sop


# ── GET /api/v1/sops ──────────────────────────────────────────

class TestListSOPs:
    def test_requires_auth(self, client):
        resp = client.get("/api/v1/sops")
        assert resp.status_code in (401, 403)

    def test_returns_list(self, client, staff_token, db, staff_user, test_dept):
        _make_active_sop(db, staff_user, test_dept, "list-sop-1")
        resp = client.get("/api/v1/sops", headers=_auth(staff_token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_filter_by_status(self, client, staff_token, db, staff_user, test_dept):
        _make_draft_sop(db, staff_user, test_dept, "list-draft-1")
        resp = client.get("/api/v1/sops?status=draft", headers=_auth(staff_token))
        assert resp.status_code == 200
        for sop in resp.json():
            assert sop["status"] == "draft"


# ── GET /api/v1/sops/{sop_id} ─────────────────────────────────

class TestGetSOP:
    def test_returns_sop(self, client, staff_token, db, staff_user, test_dept):
        sop = _make_active_sop(db, staff_user, test_dept, "get-sop-1")
        resp = client.get(f"/api/v1/sops/{sop.id}", headers=_auth(staff_token))
        assert resp.status_code == 200
        assert resp.json()["id"] == sop.id

    def test_404_for_unknown_id(self, client, staff_token):
        resp = client.get("/api/v1/sops/nonexistent-id", headers=_auth(staff_token))
        assert resp.status_code == 404


# ── PUT /api/v1/sops/{sop_id} ─────────────────────────────────

class TestUpdateSOP:
    def test_updates_title(self, client, staff_token, db, staff_user, test_dept):
        sop = _make_draft_sop(db, staff_user, test_dept, "update-sop-1")
        resp = client.put(
            f"/api/v1/sops/{sop.id}",
            json={"title": "수정된 제목"},
            headers=_auth(staff_token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "수정된 제목"

    def test_cannot_update_active_sop(self, client, staff_token, db, staff_user, test_dept):
        sop = _make_active_sop(db, staff_user, test_dept, "update-active-1")
        resp = client.put(
            f"/api/v1/sops/{sop.id}",
            json={"title": "변경 시도"},
            headers=_auth(staff_token),
        )
        assert resp.status_code == 409


# ── POST /api/v1/sops/{sop_id}/publish ───────────────────────

class TestPublishSOP:
    def test_staff_cannot_publish(self, client, staff_token, db, staff_user, test_dept):
        sop = _make_draft_sop(db, staff_user, test_dept, "pub-staff-1")
        resp = client.post(f"/api/v1/sops/{sop.id}/publish", headers=_auth(staff_token))
        assert resp.status_code == 403

    def test_manager_can_publish(self, client, manager_token, db, manager_user, test_dept):
        sop = _make_draft_sop(db, manager_user, test_dept, "pub-mgr-1")
        with patch("app.tasks.sop_tasks.ingest_sop_task") as mock_task:
            mock_task.delay = MagicMock()
            resp = client.post(f"/api/v1/sops/{sop.id}/publish", headers=_auth(manager_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    def test_cannot_publish_already_active(self, client, manager_token, db, manager_user, test_dept):
        sop = _make_active_sop(db, manager_user, test_dept, "pub-active-1")
        resp = client.post(f"/api/v1/sops/{sop.id}/publish", headers=_auth(manager_token))
        assert resp.status_code == 409


# ── DELETE /api/v1/sops/{sop_id} (archive) ───────────────────

class TestArchiveSOP:
    def test_staff_cannot_archive(self, client, staff_token, db, staff_user, test_dept):
        sop = _make_active_sop(db, staff_user, test_dept, "arch-staff-1")
        resp = client.delete(f"/api/v1/sops/{sop.id}", headers=_auth(staff_token))
        assert resp.status_code == 403

    def test_manager_can_archive(self, client, manager_token, db, manager_user, test_dept):
        sop = _make_active_sop(db, manager_user, test_dept, "arch-mgr-1")
        resp = client.delete(f"/api/v1/sops/{sop.id}", headers=_auth(manager_token))
        assert resp.status_code == 204


# ── GET /api/v1/sops/{sop_id}/export ─────────────────────────

class TestExportSOP:
    def test_export_pdf(self, client, staff_token, db, staff_user, test_dept):
        sop = _make_active_sop(db, staff_user, test_dept, "export-pdf-1")
        resp = client.get(f"/api/v1/sops/{sop.id}/export?format=pdf", headers=_auth(staff_token))
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content[:4] == b"%PDF"

    def test_export_checklist_csv(self, client, staff_token, db, staff_user, test_dept):
        sop = _make_active_sop(db, staff_user, test_dept, "export-csv-1")
        resp = client.get(f"/api/v1/sops/{sop.id}/export?format=checklist", headers=_auth(staff_token))
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

    def test_invalid_format_returns_400(self, client, staff_token, db, staff_user, test_dept):
        sop = _make_active_sop(db, staff_user, test_dept, "export-bad-1")
        resp = client.get(f"/api/v1/sops/{sop.id}/export?format=xlsx", headers=_auth(staff_token))
        assert resp.status_code == 400


# ── POST /api/v1/sops/{sop_id}/acknowledge ───────────────────

class TestAcknowledgeSOP:
    def test_staff_can_acknowledge(self, client, staff_token, db, staff_user, test_dept):
        sop = _make_active_sop(db, staff_user, test_dept, "ack-test-1")
        resp = client.post(f"/api/v1/sops/{sop.id}/acknowledge", headers=_auth(staff_token))
        assert resp.status_code == 201
        assert resp.json()["sop_id"] == sop.id

    def test_cannot_acknowledge_draft(self, client, staff_token, db, staff_user, test_dept):
        sop = _make_draft_sop(db, staff_user, test_dept, "ack-draft-1")
        resp = client.post(f"/api/v1/sops/{sop.id}/acknowledge", headers=_auth(staff_token))
        assert resp.status_code == 409

    def test_duplicate_acknowledge_idempotent(self, client, staff_token, db, staff_user, test_dept):
        sop = _make_active_sop(db, staff_user, test_dept, "ack-dup-1")
        resp1 = client.post(f"/api/v1/sops/{sop.id}/acknowledge", headers=_auth(staff_token))
        resp2 = client.post(f"/api/v1/sops/{sop.id}/acknowledge", headers=_auth(staff_token))
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["sop_id"] == resp2.json()["sop_id"]


# ── GET /api/v1/sops/{sop_id}/acknowledge-stats ──────────────

class TestAcknowledgeStats:
    def test_staff_cannot_view_stats(self, client, staff_token, db, staff_user, test_dept):
        sop = _make_active_sop(db, staff_user, test_dept, "stats-staff-1")
        resp = client.get(f"/api/v1/sops/{sop.id}/acknowledge-stats", headers=_auth(staff_token))
        assert resp.status_code == 403

    def test_manager_can_view_stats(self, client, manager_token, db, manager_user, test_dept):
        sop = _make_active_sop(db, manager_user, test_dept, "stats-mgr-1")
        resp = client.get(f"/api/v1/sops/{sop.id}/acknowledge-stats", headers=_auth(manager_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "total_staff" in data
        assert "acknowledged" in data
        assert "completion_rate" in data
