"""Work Order API 엔드포인트 테스트 (WO-F01, F02, F30, F31, F41, F42)"""

from unittest.mock import MagicMock, patch

import pytest


# ── 헬퍼 ─────────────────────────────────────────────────────


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def make_wo(
    wo_id="wo-test-1",
    wo_number="WO-2026-001",
    status="open",
    severity="high",
    category="전기",
    room_no="503",
    reported_by=1,
):
    return {
        "id": wo_id,
        "wo_number": wo_number,
        "room_no": room_no,
        "category": category,
        "description": "욕실 조명 불량",
        "ai_category": category,
        "ai_severity": severity,
        "severity": severity,
        "status": status,
        "reported_by": reported_by,
        "reported_at": "2026-03-29T09:00:00",
        "assigned_to": None,
        "sla_deadline": "2026-03-29T13:00:00",
        "history": [{"status": "접수", "changed_by": reported_by, "changed_at": "2026-03-29T09:00:00", "note": None}],
        "photo_urls": [],
        "parts_used": [],
        "resolution_note": None,
        "actual_duration_min": None,
        "external_vendor": None,
        "escalated": False,
    }


# ── WO-F01: 신고 접수 ────────────────────────────────────────


class TestCreateWorkOrder:
    def test_create_requires_auth(self, client):
        resp = client.post("/api/v1/work-orders", json={
            "room_no": "503", "description": "조명 불량", "category": "전기",
        })
        assert resp.status_code in (401, 403)

    def test_create_success(self, client, staff_token):
        mock_wo = make_wo()
        with patch("app.api.routes.work_orders.WorkOrderService") as mock_svc_cls:
            mock_svc = MagicMock()
            mock_svc.create_work_order.return_value = mock_wo
            mock_svc_cls.return_value = mock_svc

            resp = client.post(
                "/api/v1/work-orders",
                json={"room_no": "503", "description": "욕실 조명 불량", "category": "전기"},
                headers=auth_headers(staff_token),
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["wo_number"].startswith("WO-")
        assert data["status"] == "open"

    def test_create_missing_description_returns_422(self, client, staff_token):
        resp = client.post(
            "/api/v1/work-orders",
            json={"room_no": "503"},
            headers=auth_headers(staff_token),
        )
        assert resp.status_code == 422

    def test_create_returns_sla_deadline(self, client, staff_token):
        mock_wo = make_wo()
        with patch("app.api.routes.work_orders.WorkOrderService") as mock_svc_cls:
            mock_svc_cls.return_value.create_work_order.return_value = mock_wo
            resp = client.post(
                "/api/v1/work-orders",
                json={"room_no": "101", "description": "에어컨 고장", "category": "에어컨"},
                headers=auth_headers(staff_token),
            )

        assert resp.status_code == 201
        assert resp.json()["sla_deadline"] is not None


# ── WO-F30: 상태 변경 ────────────────────────────────────────


class TestUpdateStatus:
    def test_update_status_to_in_progress(self, client, staff_token):
        updated_wo = make_wo(status="in_progress")
        with patch("app.api.routes.work_orders.WorkOrderService") as mock_svc_cls:
            mock_svc = MagicMock()
            mock_svc.update_status.return_value = updated_wo
            mock_svc_cls.return_value = mock_svc

            resp = client.patch(
                "/api/v1/work-orders/wo-test-1/status",
                json={"status": "in_progress"},
                headers=auth_headers(staff_token),
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

    def test_invalid_status_returns_422(self, client, staff_token):
        resp = client.patch(
            "/api/v1/work-orders/wo-test-1/status",
            json={"status": "invalid_status"},
            headers=auth_headers(staff_token),
        )
        assert resp.status_code == 422

    def test_invalid_transition_returns_400(self, client, staff_token):
        with patch("app.api.routes.work_orders.WorkOrderService") as mock_svc_cls:
            mock_svc = MagicMock()
            mock_svc.update_status.side_effect = ValueError("유효하지 않은 상태 전환")
            mock_svc_cls.return_value = mock_svc

            resp = client.patch(
                "/api/v1/work-orders/wo-test-1/status",
                json={"status": "open"},
                headers=auth_headers(staff_token),
            )

        assert resp.status_code == 400


# ── WO-F31: 완료 처리 ────────────────────────────────────────


class TestCompleteWorkOrder:
    def test_complete_success(self, client, staff_token):
        completed_wo = make_wo(status="completed")
        with patch("app.api.routes.work_orders.WorkOrderService") as mock_svc_cls:
            mock_svc_cls.return_value.complete_work_order.return_value = completed_wo
            resp = client.patch(
                "/api/v1/work-orders/wo-test-1/complete",
                json={
                    "resolution_note": "형광등 교체 완료",
                    "actual_duration_min": 30,
                    "parts_used": [{"name": "형광등", "qty": 2}],
                },
                headers=auth_headers(staff_token),
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_complete_missing_resolution_note_returns_422(self, client, staff_token):
        resp = client.patch(
            "/api/v1/work-orders/wo-test-1/complete",
            json={"actual_duration_min": 30},
            headers=auth_headers(staff_token),
        )
        assert resp.status_code == 422

    def test_complete_missing_duration_returns_422(self, client, staff_token):
        resp = client.patch(
            "/api/v1/work-orders/wo-test-1/complete",
            json={"resolution_note": "완료"},
            headers=auth_headers(staff_token),
        )
        assert resp.status_code == 422


# ── 목록 조회 및 필터 ────────────────────────────────────────


class TestListWorkOrders:
    def test_list_requires_auth(self, client):
        resp = client.get("/api/v1/work-orders")
        assert resp.status_code in (401, 403)

    def test_list_returns_array(self, client, staff_token):
        with patch("app.api.routes.work_orders.WorkOrderService") as mock_svc_cls:
            mock_svc_cls.return_value.list_work_orders.return_value = [make_wo()]
            resp = client.get(
                "/api/v1/work-orders",
                headers=auth_headers(staff_token),
            )

        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_filter_by_severity(self, client, staff_token):
        with patch("app.api.routes.work_orders.WorkOrderService") as mock_svc_cls:
            mock_svc = MagicMock()
            mock_svc.list_work_orders.return_value = []
            mock_svc_cls.return_value = mock_svc

            resp = client.get(
                "/api/v1/work-orders?severity=critical",
                headers=auth_headers(staff_token),
            )
            assert resp.status_code == 200
            mock_svc.list_work_orders.assert_called_once()
            call_kwargs = mock_svc.list_work_orders.call_args[1]
            assert call_kwargs.get("severity") == "critical"

    def test_list_filter_by_status(self, client, staff_token):
        with patch("app.api.routes.work_orders.WorkOrderService") as mock_svc_cls:
            mock_svc = MagicMock()
            mock_svc.list_work_orders.return_value = []
            mock_svc_cls.return_value = mock_svc

            resp = client.get(
                "/api/v1/work-orders?status=open",
                headers=auth_headers(staff_token),
            )
            assert resp.status_code == 200


# ── WO-F41: 통계 조회 ────────────────────────────────────────


class TestStats:
    def test_stats_requires_auth(self, client):
        """비인증 요청은 401"""
        resp = client.get("/api/v1/work-orders/stats")
        assert resp.status_code in (401, 403)

    def test_stats_returns_summary(self, client, manager_token):
        mock_stats = {
            "total": 10,
            "by_severity": {"critical": 1, "high": 3, "medium": 4, "low": 2},
            "by_status": {"open": 5, "in_progress": 3, "completed": 2},
            "by_category": {"전기": 3, "에어컨": 2, "배관": 1, "가구": 1, "청결": 2, "기타": 1},
            "avg_completion_min": 87.5,
            "sla_breach_count": 2,
        }
        with patch("app.api.routes.work_orders.WorkOrderService") as mock_svc_cls:
            mock_svc_cls.return_value.get_stats.return_value = mock_stats
            resp = client.get(
                "/api/v1/work-orders/stats",
                headers=auth_headers(manager_token),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "by_severity" in data
        assert "avg_completion_min" in data


# ── WO-F42: 주간 KPI 리포트 ─────────────────────────────────


class TestWeeklyKPI:
    def test_kpi_returns_five_metrics(self, client, manager_token):
        mock_kpi = {
            "avg_completion_min": 95.0,
            "sla_compliance_rate": 0.87,
            "escalation_count": 3,
            "repeat_fault_top5": [
                {"location": "503", "category": "전기", "count": 4}
            ],
            "total_work_orders": 42,
        }
        with patch("app.api.routes.work_orders.WorkOrderService") as mock_svc_cls:
            mock_svc_cls.return_value.get_weekly_kpi.return_value = mock_kpi
            resp = client.get(
                "/api/v1/work-orders/kpi",
                headers=auth_headers(manager_token),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "avg_completion_min" in data
        assert "sla_compliance_rate" in data
        assert "escalation_count" in data
        assert "repeat_fault_top5" in data
        assert "total_work_orders" in data
