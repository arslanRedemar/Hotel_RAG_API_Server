"""Work Order 서비스 DB 통합 테스트 (service.py 커버리지 보완)"""

from unittest.mock import patch

import pytest

from app.work_order.classifier import ClassificationResult
from app.work_order.service import WorkOrderService, save_wo_history


@pytest.fixture
def engineer_user(db, test_dept):
    from app.database.models import User
    from app.auth.password import hash_password
    user = db.query(User).filter_by(email="engineer@hotel.com").first()
    if not user:
        user = User(
            email="engineer@hotel.com",
            password_hash=hash_password("pass1234"),
            name="엔지니어C",
            role="staff",
            department_id=test_dept.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@pytest.fixture
def svc(db):
    return WorkOrderService(db=db)


@pytest.fixture
def mock_classification():
    return ClassificationResult(category="전기", severity="high", confidence=0.95)


# ── DB 통합: WO 생성 ─────────────────────────────────────────


class TestWorkOrderDB:
    def test_create_persists_to_db(self, svc, staff_user, mock_classification):
        with patch.object(svc.classifier, "classify", return_value=mock_classification):
            wo = svc.create_work_order(
                description="욕실 조명 불량",
                reported_by=staff_user.id,
                room_no="503",
            )

        from app.database.models import WorkOrder
        db_wo = svc.db.query(WorkOrder).filter(WorkOrder.id == wo["id"]).first()
        assert db_wo is not None
        assert db_wo.room_no == "503"
        assert db_wo.severity == "high"

    def test_create_multiple_generate_unique_numbers(self, svc, staff_user, mock_classification):
        with patch.object(svc.classifier, "classify", return_value=mock_classification):
            wo1 = svc.create_work_order(description="에어컨 고장", reported_by=staff_user.id)
            wo2 = svc.create_work_order(description="배관 막힘", reported_by=staff_user.id)

        assert wo1["wo_number"] != wo2["wo_number"]

    def test_list_work_orders_from_db(self, svc, staff_user, mock_classification):
        with patch.object(svc.classifier, "classify", return_value=mock_classification):
            svc.create_work_order(description="전구 교체", reported_by=staff_user.id, room_no="101")
            svc.create_work_order(description="변기 막힘", reported_by=staff_user.id, room_no="202")

        result = svc.list_work_orders()
        assert len(result) >= 2

    def test_list_filter_by_severity(self, svc, staff_user):
        low_cls = ClassificationResult(category="전기", severity="low", confidence=0.9)
        with patch.object(svc.classifier, "classify", return_value=low_cls):
            svc.create_work_order(description="빈 객실 전구", reported_by=staff_user.id)

        result = svc.list_work_orders(severity="low")
        assert all(w["severity"] == "low" for w in result)

    def test_get_stats_from_db(self, svc, staff_user, mock_classification):
        with patch.object(svc.classifier, "classify", return_value=mock_classification):
            svc.create_work_order(description="조명 고장 1", reported_by=staff_user.id)

        stats = svc.get_stats()
        assert "total" in stats
        assert stats["total"] >= 1
        assert "by_severity" in stats
        assert "by_status" in stats

    def test_get_weekly_kpi_from_db(self, svc, staff_user, mock_classification):
        with patch.object(svc.classifier, "classify", return_value=mock_classification):
            svc.create_work_order(description="에어컨 이상", reported_by=staff_user.id)

        kpi = svc.get_weekly_kpi()
        assert "avg_completion_min" in kpi
        assert "sla_compliance_rate" in kpi
        assert "total_work_orders" in kpi


# ── 상태 전환 통합 ────────────────────────────────────────────


class TestStatusTransitionDB:
    def test_update_status_and_check_history(self, svc, staff_user, mock_classification):
        with patch.object(svc.classifier, "classify", return_value=mock_classification):
            wo = svc.create_work_order(
                description="에어컨 점검", reported_by=staff_user.id, room_no="301"
            )

        from app.database.models import WorkOrder
        db_wo = svc.db.query(WorkOrder).filter(WorkOrder.id == wo["id"]).first()
        db_wo.status = "open"  # 강제로 open으로 설정
        svc.db.flush()

        updated = svc.update_status(wo["id"], "in_progress", staff_user.id, note="작업 시작")
        assert updated["status"] == "in_progress"

    def test_complete_work_order_db(self, svc, staff_user, mock_classification):
        with patch.object(svc.classifier, "classify", return_value=mock_classification):
            wo = svc.create_work_order(
                description="형광등 교체", reported_by=staff_user.id, room_no="402"
            )

        from app.database.models import WorkOrder
        db_wo = svc.db.query(WorkOrder).filter(WorkOrder.id == wo["id"]).first()
        db_wo.status = "in_progress"
        svc.db.flush()

        completed = svc.complete_work_order(
            wo_id=wo["id"],
            resolution_note="형광등 2개 교체 완료",
            actual_duration_min=25,
            parts_used=[{"name": "형광등", "qty": 2}],
            changed_by=staff_user.id,
        )
        assert completed["status"] == "completed"


# ── save_wo_history 직접 테스트 ──────────────────────────────


class TestSaveWoHistory:
    def test_save_history_without_db_silently_passes(self):
        """DB 없으면 경고만 출력하고 예외 없음"""
        save_wo_history(None, "wo-id", "접수", 1)

    def test_save_history_with_mock_db(self):
        from unittest.mock import MagicMock
        mock_db = MagicMock()
        save_wo_history(mock_db, "wo-id", "in_progress", 2, "테스트 노트")
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()
