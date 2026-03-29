"""Compliance & Audit API 엔드포인트 테스트 (CA-F01~F42)"""

from unittest.mock import MagicMock, patch



def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── 헬퍼 ─────────────────────────────────────────────────────


def make_template(
    template_id="tpl-test-1",
    name="주방 위생 점검표",
    type_="위생",
    frequency="daily",
):
    return {
        "id": template_id,
        "name": name,
        "type": type_,
        "frequency": frequency,
        "frequency_day": None,
        "department_id": None,
        "legal_reference": "식품위생법",
        "is_active": True,
        "items": [
            {
                "id": "h-001",
                "category": "온도",
                "description": "냉장고 온도",
                "required": True,
                "photo_required_on_ng": True,
            }
        ],
    }


def make_record(record_id="rec-1", overall_result="pass", ng_count=0):
    return {
        "id": record_id,
        "template_id": "tpl-test-1",
        "location": "주방 A",
        "inspector_id": 1,
        "inspector_name": "박민수",
        "inspected_at": "2026-03-29T08:00:00",
        "submitted_at": "2026-03-29T08:30:00",
        "overall_result": overall_result,
        "ng_count": ng_count,
        "signature": "박민수 | 2026-03-29T08:30:00",
        "items": [],
        "corrective_actions": [],
    }


# ── CA-F04: 템플릿 CRUD ───────────────────────────────────────


class TestTemplateAPI:
    def test_create_template_requires_auth(self, client):
        resp = client.post(
            "/api/v1/inspection-templates",
            json=make_template(),
        )
        assert resp.status_code in (401, 403)

    def test_create_template_success(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.create_template.return_value = make_template()
            mock_cls.return_value = mock_svc

            resp = client.post(
                "/api/v1/inspection-templates",
                json={
                    "name": "주방 위생 점검표",
                    "type": "위생",
                    "frequency": "daily",
                    "items": [
                        {
                            "id": "h-001",
                            "category": "온도",
                            "description": "냉장고 온도",
                            "required": True,
                            "photo_required_on_ng": True,
                        }
                    ],
                },
                headers=auth_headers(staff_token),
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "주방 위생 점검표"
        assert data["type"] == "위생"

    def test_create_template_missing_name_returns_422(self, client, staff_token):
        resp = client.post(
            "/api/v1/inspection-templates",
            json={"type": "위생", "frequency": "daily", "items": []},
            headers=auth_headers(staff_token),
        )
        assert resp.status_code == 422

    def test_list_templates(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.list_templates.return_value = [make_template()]
            resp = client.get(
                "/api/v1/inspection-templates",
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_templates_filter_by_type(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.list_templates.return_value = []
            mock_cls.return_value = mock_svc

            resp = client.get(
                "/api/v1/inspection-templates?type=위생",
                headers=auth_headers(staff_token),
            )
            assert resp.status_code == 200
            call_kwargs = mock_svc.list_templates.call_args[1]
            assert call_kwargs.get("type") == "위생"

    def test_get_template_by_id(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.get_template.return_value = make_template()
            resp = client.get(
                "/api/v1/inspection-templates/tpl-test-1",
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == "tpl-test-1"

    def test_get_nonexistent_template_returns_404(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.get_template.return_value = None
            resp = client.get(
                "/api/v1/inspection-templates/nonexistent",
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 404


# ── CA-F10: 스케줄 ────────────────────────────────────────────


class TestScheduleAPI:
    def test_list_schedules_requires_auth(self, client):
        resp = client.get("/api/v1/inspection-schedules")
        assert resp.status_code in (401, 403)

    def test_list_schedules_returns_array(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.get_schedules.return_value = [
                {
                    "id": 1,
                    "template_id": "tpl-1",
                    "scheduled_date": "2026-03-29",
                    "status": "scheduled",
                    "assigned_to": None,
                }
            ]
            resp = client.get(
                "/api/v1/inspection-schedules",
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_today_schedules(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.get_today_schedules.return_value = []
            resp = client.get(
                "/api/v1/inspection-schedules/today",
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 200

    def test_generate_schedules_for_template(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.generate_schedules.return_value = [
                {"id": 1, "template_id": "tpl-1", "scheduled_date": "2026-04-01", "status": "scheduled"}
            ]
            resp = client.post(
                "/api/v1/inspection-templates/tpl-1/schedules",
                json={"months": 3},
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 200


# ── CA-F01~F06: 점검 기록 ────────────────────────────────────


class TestRecordAPI:
    def test_submit_record_requires_auth(self, client):
        resp = client.post("/api/v1/inspection-records", json={})
        assert resp.status_code in (401, 403)

    def test_submit_record_success(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.submit_record.return_value = make_record()
            resp = client.post(
                "/api/v1/inspection-records",
                json={
                    "template_id": "tpl-test-1",
                    "location": "주방 A",
                    "inspected_at": "2026-03-29T08:00:00",
                    "items": [
                        {"item_id": "h-001", "result": "OK", "note": None, "photo_url": None}
                    ],
                },
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["overall_result"] == "pass"
        assert "signature" in data

    def test_submit_ng_without_note_returns_400(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.submit_record.side_effect = ValueError(
                "NG 항목에 비고가 필요합니다"
            )
            resp = client.post(
                "/api/v1/inspection-records",
                json={
                    "template_id": "tpl-test-1",
                    "location": "주방",
                    "inspected_at": "2026-03-29T08:00:00",
                    "items": [
                        {"item_id": "h-001", "result": "NG", "note": None, "photo_url": None}
                    ],
                },
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 400

    def test_submit_missing_template_id_returns_422(self, client, staff_token):
        resp = client.post(
            "/api/v1/inspection-records",
            json={"location": "주방", "items": []},
            headers=auth_headers(staff_token),
        )
        assert resp.status_code == 422

    def test_get_record_by_id(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.get_record.return_value = make_record()
            resp = client.get(
                "/api/v1/inspection-records/rec-1",
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == "rec-1"

    def test_get_nonexistent_record_returns_404(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.get_record.return_value = None
            resp = client.get(
                "/api/v1/inspection-records/nonexistent",
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 404

    def test_list_records_returns_array(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.list_records.return_value = [make_record()]
            resp = client.get(
                "/api/v1/inspection-records",
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_records_filter_by_type(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.list_records.return_value = []
            mock_cls.return_value = mock_svc
            resp = client.get(
                "/api/v1/inspection-records?type=위생",
                headers=auth_headers(staff_token),
            )
            assert resp.status_code == 200


# ── CA-F06: 불변성 + 정정 이력 ────────────────────────────────


class TestCorrectiveActionAPI:
    def test_add_corrective_action_success(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.add_corrective_action.return_value = {
                "id": 1,
                "record_id": "rec-1",
                "item_id": "h-001",
                "action": "냉장고 온도 재설정",
                "completed_by": 1,
                "completed_at": "2026-03-29T10:00:00",
            }
            resp = client.post(
                "/api/v1/inspection-records/rec-1/corrective-actions",
                json={
                    "item_id": "h-001",
                    "action": "냉장고 온도 재설정",
                },
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 201
        assert resp.json()["item_id"] == "h-001"

    def test_get_corrective_actions(self, client, staff_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.get_corrective_actions.return_value = []
            resp = client.get(
                "/api/v1/inspection-records/rec-1/corrective-actions",
                headers=auth_headers(staff_token),
            )
        assert resp.status_code == 200


# ── CA-F20~F21: 이상 감지 ─────────────────────────────────────


class TestAnomalyAPI:
    def test_get_anomalies_requires_auth(self, client):
        resp = client.get("/api/v1/inspections/anomalies")
        assert resp.status_code in (401, 403)

    def test_get_anomalies_returns_array(self, client, manager_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            with patch("app.api.routes.inspections.AnomalyDetector") as mock_det:
                mock_cls.return_value.list_records.return_value = []
                mock_det.return_value.analyze_all.return_value = [
                    {
                        "type": "repeat_ng",
                        "severity": "medium",
                        "item_id": "h-001",
                        "ng_count": 3,
                        "recommendation": "점검 필요",
                    }
                ]
                resp = client.get(
                    "/api/v1/inspections/anomalies",
                    headers=auth_headers(manager_token),
                )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ── CA-F30~32: 감사 보고서 ────────────────────────────────────


class TestReportAPI:
    def test_get_stats_returns_summary(self, client, manager_token):
        mock_stats = {
            "total_inspections": 30,
            "pass_count": 25,
            "conditional_pass_count": 4,
            "fail_count": 1,
            "pass_rate_pct": 83.3,
            "total_items_checked": 300,
            "total_ng_count": 12,
            "ng_rate_pct": 4.0,
        }
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.get_stats.return_value = mock_stats
            resp = client.get(
                "/api/v1/inspection-reports/stats",
                headers=auth_headers(manager_token),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_inspections" in data
        assert "pass_rate_pct" in data
        assert "ng_rate_pct" in data

    def test_generate_report_returns_pdf(self, client, manager_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            with patch("app.api.routes.inspections.InspectionReportGenerator") as mock_gen:
                mock_cls.return_value.list_records.return_value = [
                    make_record("r1", "pass", 0)
                ]
                mock_gen.return_value.generate.return_value = b"%PDF-1.4 test content"
                resp = client.post(
                    "/api/v1/inspection-reports/generate",
                    json={
                        "from_date": "2026-01-01",
                        "to_date": "2026-03-29",
                        "types": ["위생"],
                    },
                    headers=auth_headers(manager_token),
                )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    def test_generate_report_no_records_returns_404(self, client, manager_token):
        with patch("app.api.routes.inspections.InspectionService") as mock_cls:
            mock_cls.return_value.list_records.return_value = []
            resp = client.post(
                "/api/v1/inspection-reports/generate",
                json={"from_date": "2026-01-01", "to_date": "2026-01-31"},
                headers=auth_headers(manager_token),
            )
        assert resp.status_code == 404

    def test_generate_report_requires_auth(self, client):
        resp = client.post(
            "/api/v1/inspection-reports/generate",
            json={"from_date": "2026-01-01", "to_date": "2026-03-29"},
        )
        assert resp.status_code in (401, 403)
