"""Work Order 서비스 레이어 테스트 (WO-F01, F13, F20, F30, F31, F40)"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.work_order.classifier import ClassificationResult
from app.work_order.service import WorkOrderService


# ── 픽스처 ──────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_notifier():
    return MagicMock()


@pytest.fixture
def service(mock_db, mock_notifier):
    svc = WorkOrderService(db=mock_db)
    svc.notifier = mock_notifier
    return svc


@pytest.fixture
def sample_wo_data():
    return {
        "room_no": "503",
        "description": "욕실 조명 점등 불가",
        "category": "전기",
        "severity": "high",
        "reported_by": 1,
    }


@pytest.fixture
def mock_classification():
    return ClassificationResult(category="전기", severity="high", confidence=0.95)


# ── WO-F01: Work Order 생성 ──────────────────────────────────


class TestCreateWorkOrder:
    def test_create_returns_wo_with_unique_number(self, service, sample_wo_data, mock_classification):
        with patch.object(service.classifier, "classify", return_value=mock_classification):
            with patch("app.work_order.service.AutoAssigner") as mock_assigner_cls:
                mock_assigner = MagicMock()
                mock_assigner.assign.return_value = None
                mock_assigner_cls.return_value = mock_assigner

                wo = service.create_work_order(**sample_wo_data)

        assert wo["wo_number"].startswith("WO-")
        assert wo["status"] == "open"
        assert wo["room_no"] == "503"

    def test_create_sets_ai_classification(self, service, sample_wo_data, mock_classification):
        with patch.object(service.classifier, "classify", return_value=mock_classification):
            with patch("app.work_order.service.AutoAssigner") as mock_assigner_cls:
                mock_assigner_cls.return_value.assign.return_value = None
                wo = service.create_work_order(**sample_wo_data)

        assert wo["ai_category"] == "전기"
        assert wo["ai_severity"] == "high"

    def test_create_sets_sla_deadline(self, service, sample_wo_data, mock_classification):
        with patch.object(service.classifier, "classify", return_value=mock_classification):
            with patch("app.work_order.service.AutoAssigner") as mock_assigner_cls:
                mock_assigner_cls.return_value.assign.return_value = None
                wo = service.create_work_order(**sample_wo_data)

        assert wo["sla_deadline"] is not None

    def test_create_adds_initial_history(self, service, sample_wo_data, mock_classification):
        with patch.object(service.classifier, "classify", return_value=mock_classification):
            with patch("app.work_order.service.AutoAssigner") as mock_assigner_cls:
                mock_assigner_cls.return_value.assign.return_value = None
                wo = service.create_work_order(**sample_wo_data)

        assert len(wo["history"]) >= 1
        assert wo["history"][0]["status"] == "접수"

    def test_create_triggers_auto_assign(self, service, sample_wo_data, mock_classification):
        with patch.object(service.classifier, "classify", return_value=mock_classification):
            with patch("app.work_order.service.AutoAssigner") as mock_assigner_cls:
                mock_assigner = MagicMock()
                mock_assigner_cls.return_value = mock_assigner
                service.create_work_order(**sample_wo_data)

        mock_assigner.assign.assert_called_once()


# ── WO-F13: 분류 수정 이력 기록 ─────────────────────────────


class TestUpdateCategory:
    def test_update_category_records_history(self, service, mock_db):
        mock_wo = {
            "id": "test-id",
            "category": "기타",
            "severity": "medium",
            "history": [],
        }
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
            id="test-id", category="기타", severity="medium",
            history=[], to_dict=lambda: mock_wo
        )

        with patch("app.work_order.service.save_wo_history") as mock_hist:
            service.update_category("test-id", new_category="전기", changed_by=1)
            mock_hist.assert_called_once()

    def test_update_category_invalid_category_raises(self, service):
        with pytest.raises(ValueError, match="유효하지 않은 카테고리"):
            service.update_category("test-id", new_category="없는카테고리", changed_by=1)


# ── WO-F30: 상태 전환 ────────────────────────────────────────


class TestStatusTransition:
    VALID_TRANSITIONS = [
        ("open", "in_progress"),
        ("open", "on_hold"),
        ("assigned", "in_progress"),
        ("in_progress", "completed"),
        ("in_progress", "on_hold"),
        ("on_hold", "in_progress"),
    ]
    INVALID_TRANSITIONS = [
        ("completed", "in_progress"),
        ("cancelled", "open"),
    ]

    @pytest.mark.parametrize("from_status,to_status", VALID_TRANSITIONS)
    def test_valid_transitions_succeed(self, service, from_status, to_status):
        assert service.is_valid_transition(from_status, to_status) is True

    @pytest.mark.parametrize("from_status,to_status", INVALID_TRANSITIONS)
    def test_invalid_transitions_raise(self, service, from_status, to_status):
        assert service.is_valid_transition(from_status, to_status) is False


# ── WO-F31: 완료 처리 필수 필드 ─────────────────────────────


class TestCompleteWorkOrder:
    def test_complete_requires_resolution_note(self, service):
        with pytest.raises(ValueError, match="resolution_note"):
            service.validate_completion_data(
                resolution_note=None,
                actual_duration_min=60,
                parts_used=[],
            )

    def test_complete_requires_duration(self, service):
        with pytest.raises(ValueError, match="actual_duration_min"):
            service.validate_completion_data(
                resolution_note="조명 교체 완료",
                actual_duration_min=None,
                parts_used=[],
            )

    def test_complete_allows_empty_parts(self, service):
        # parts_used는 빈 리스트 허용
        service.validate_completion_data(
            resolution_note="조명 교체 완료",
            actual_duration_min=30,
            parts_used=[],
        )

    def test_complete_duration_must_be_positive(self, service):
        with pytest.raises(ValueError):
            service.validate_completion_data(
                resolution_note="완료",
                actual_duration_min=-1,
                parts_used=[],
            )


# ── WO-F40: 이력 자동 기록 ──────────────────────────────────


class TestHistoryTracking:
    def test_status_change_appends_to_history(self, service):
        history = []
        entry = service.build_history_entry(
            status="in_progress",
            changed_by=1,
            note="작업 시작",
        )
        history.append(entry)

        assert history[0]["status"] == "in_progress"
        assert history[0]["changed_by"] == 1
        assert "changed_at" in history[0]

    def test_history_entry_has_required_fields(self, service):
        entry = service.build_history_entry(status="completed", changed_by=2)
        assert "status" in entry
        assert "changed_by" in entry
        assert "changed_at" in entry

    def test_system_action_uses_none_as_changed_by(self, service):
        entry = service.build_history_entry(status="assigned", changed_by=None, note="자동 배정")
        assert entry["changed_by"] is None
        assert entry["note"] == "자동 배정"
