"""Work Order 자동 배정 엔진 테스트 (WO-F20, F21, F22, F23)"""

from unittest.mock import MagicMock, patch

import pytest

from app.work_order.assigner import AutoAssigner, SLAConfig


# ── 픽스처 ──────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def assigner(mock_db):
    return AutoAssigner(db=mock_db)


@pytest.fixture
def make_engineer():
    def _make(user_id, categories, available=True):
        u = MagicMock()
        u.id = user_id
        u.email = f"eng{user_id}@hotel.com"
        u.name = f"엔지니어{user_id}"
        cap = MagicMock()
        cap.categories = categories
        cap.is_available = available
        cap.priority = 1
        u.capability = cap
        return u
    return _make


# ── WO-F20: 자동 배정 ────────────────────────────────────────


class TestAutoAssign:
    def test_assigns_to_available_engineer_by_category(self, assigner, make_engineer):
        engineers = [make_engineer(1, ["전기", "에어컨"])]
        with patch.object(assigner, "_get_candidates", return_value=engineers):
            with patch.object(assigner, "_notify_assignee") as mock_notify:
                result = assigner.assign(wo_id="wo-1", category="전기", severity="high")

        assert result is not None
        assert result["assigned_to"] == 1

    def test_skips_unavailable_engineers(self, assigner, make_engineer):
        engineers = [
            make_engineer(1, ["전기"], available=False),
            make_engineer(2, ["전기"], available=True),
        ]
        with patch.object(assigner, "_get_candidates", return_value=engineers):
            with patch.object(assigner, "_notify_assignee"):
                result = assigner.assign(wo_id="wo-1", category="전기", severity="medium")

        assert result["assigned_to"] == 2

    def test_returns_none_when_no_candidate_available(self, assigner):
        with patch.object(assigner, "_get_candidates", return_value=[]):
            result = assigner.assign(wo_id="wo-1", category="전기", severity="low")
        assert result is None

    def test_sends_notification_on_assignment(self, assigner, make_engineer):
        engineers = [make_engineer(1, ["배관"])]
        with patch.object(assigner, "_get_candidates", return_value=engineers):
            with patch.object(assigner, "_notify_assignee") as mock_notify:
                assigner.assign(wo_id="wo-1", category="배관", severity="critical")
                mock_notify.assert_called_once()


# ── WO-F21: 거절 → 재배정 ───────────────────────────────────


class TestReassignment:
    def test_reject_triggers_reassignment(self, assigner, make_engineer):
        next_engineer = make_engineer(2, ["전기"])
        with patch.object(assigner, "_get_next_candidate", return_value=next_engineer):
            with patch.object(assigner, "_notify_assignee") as mock_notify:
                result = assigner.handle_rejection(wo_id="wo-1", rejected_by=1)

        assert result["assigned_to"] == 2
        mock_notify.assert_called_once()

    def test_reject_with_no_next_candidate_escalates(self, assigner):
        with patch.object(assigner, "_get_next_candidate", return_value=None):
            with patch.object(assigner, "_escalate_to_manager") as mock_esc:
                assigner.handle_rejection(wo_id="wo-1", rejected_by=1)
                mock_esc.assert_called_once()


# ── WO-F22: SLA 에스컬레이션 ────────────────────────────────


class TestSLAEscalation:
    def test_sla_config_critical(self):
        cfg = SLAConfig.for_severity("critical")
        assert cfg.assign_limit_min == 5
        assert cfg.complete_limit_min == 120

    def test_sla_config_high(self):
        cfg = SLAConfig.for_severity("high")
        assert cfg.assign_limit_min == 15
        assert cfg.complete_limit_min == 240

    def test_sla_config_medium(self):
        cfg = SLAConfig.for_severity("medium")
        assert cfg.assign_limit_min == 60
        assert cfg.complete_limit_min == 480

    def test_sla_config_low(self):
        cfg = SLAConfig.for_severity("low")
        assert cfg.assign_limit_min == 240
        assert cfg.complete_limit_min == 4320

    def test_sla_config_unknown_severity_raises(self):
        with pytest.raises(ValueError):
            SLAConfig.for_severity("unknown")

    def test_escalation_check_overdue_wo(self, assigner):
        from datetime import datetime, timedelta, timezone
        overdue_deadline = (
            datetime.now(timezone.utc) - timedelta(minutes=10)
        ).isoformat()
        mock_wo = MagicMock()
        mock_wo.status = "assigned"
        mock_wo.accepted_at = None
        mock_wo.sla_deadline = overdue_deadline
        mock_wo.severity = "critical"

        with patch.object(assigner, "_escalate_to_manager") as mock_esc:
            assigner.check_sla_and_escalate(mock_wo)
            mock_esc.assert_called_once()

    def test_no_escalation_for_completed_wo(self, assigner):
        mock_wo = MagicMock()
        mock_wo.status = "completed"

        with patch.object(assigner, "_escalate_to_manager") as mock_esc:
            assigner.check_sla_and_escalate(mock_wo)
            mock_esc.assert_not_called()


# ── WO-F23: 외부 업체 기록 ──────────────────────────────────


class TestExternalVendor:
    def test_assign_external_vendor(self, assigner):
        result = assigner.assign_external_vendor(
            wo_id="wo-1",
            vendor_name="한국전기",
            vendor_contact="02-1234-5678",
            changed_by=1,
        )
        assert result["external_vendor"] == "한국전기"
        assert result["external_contact"] == "02-1234-5678"
