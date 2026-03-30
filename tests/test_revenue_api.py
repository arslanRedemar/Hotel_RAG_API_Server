"""Revenue Management API TDD 테스트 (RM-F01, F20~22, F30~31, F40~41)

- GET /revenue/dashboard          — RevPAR/ADR/점유율 대시보드
- GET /revenue/recommendations     — AI 요율 권고 목록
- POST /revenue/recommendations/{id}/decide — 권고 수락/수정/거절
- POST /revenue/simulate/group     — 단체 예약 시뮬레이션
- GET /revenue/forecast            — 수요 예측 조회
- POST /revenue/metrics            — 일간 성과 지표 수동 입력
- POST /revenue/events             — 로컬 이벤트 등록
"""

from datetime import date, timedelta


class TestRevenueDashboard:

    def test_dashboard_returns_summary(self, client, manager_token, db):
        """GET /revenue/dashboard — 요약 지표 반환"""
        resp = client.get(
            "/api/v1/revenue/dashboard",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "time_series" in data

    def test_dashboard_summary_has_required_fields(self, client, manager_token):
        """대시보드 summary에 RevPAR, ADR, 점유율, 총수익 포함"""
        resp = client.get(
            "/api/v1/revenue/dashboard",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert "revpar_avg" in summary
        assert "adr_avg" in summary
        assert "occupancy_avg" in summary
        assert "total_revenue" in summary

    def test_dashboard_requires_auth(self, client):
        """인증 없이 대시보드 접근 시 401/403"""
        resp = client.get("/api/v1/revenue/dashboard")
        assert resp.status_code in (401, 403)

    def test_dashboard_with_date_range(self, client, manager_token):
        """기간 파라미터 from_date/to_date 적용"""
        today = date.today()
        from_d = (today - timedelta(days=7)).isoformat()
        to_d = today.isoformat()
        resp = client.get(
            f"/api/v1/revenue/dashboard?from_date={from_d}&to_date={to_d}",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 200


class TestRevenueMetrics:

    def test_save_daily_metrics(self, client, manager_token):
        """POST /revenue/metrics — 일간 성과 지표 저장"""
        today = date.today().isoformat()
        resp = client.post(
            "/api/v1/revenue/metrics",
            json={
                "report_date": today,
                "total_rooms": 100,
                "occupied_rooms": 75,
                "occupancy_rate": 75.0,
                "adr": 120000.0,
                "revpar": 90000.0,
                "total_revenue": 9000000.0,
            },
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_duplicate_date_rejected(self, client, manager_token):
        """동일 날짜 중복 입력 시 409 또는 400"""
        today = (date.today() + timedelta(days=1)).isoformat()
        payload = {
            "report_date": today,
            "total_rooms": 100,
            "occupied_rooms": 60,
            "occupancy_rate": 60.0,
            "adr": 100000.0,
            "revpar": 60000.0,
            "total_revenue": 6000000.0,
        }
        client.post(
            "/api/v1/revenue/metrics",
            json=payload,
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        resp2 = client.post(
            "/api/v1/revenue/metrics",
            json=payload,
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp2.status_code in (400, 409)

    def test_metrics_requires_auth(self, client):
        resp = client.post("/api/v1/revenue/metrics", json={})
        assert resp.status_code in (401, 403)


class TestRevenueRecommendations:

    def test_list_recommendations(self, client, manager_token, db):
        """GET /revenue/recommendations — 권고 목록 반환"""
        resp = client.get(
            "/api/v1/revenue/recommendations",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_decide_recommendation_accept(self, client, manager_token, db):
        """POST /revenue/recommendations/{id}/decide — 권고 수락"""
        from app.database.models import RateRecommendation
        import datetime

        rec = RateRecommendation(
            recommendation_date=datetime.datetime.now(),
            stay_date=date.today() + timedelta(days=5),
            recommended_rate=150000,
            current_rate=120000,
            rate_change_pct=25.0,
            reasoning="테스트 권고",
            confidence=0.88,
            action_taken="pending",
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)

        resp = client.post(
            f"/api/v1/revenue/recommendations/{rec.id}/decide",
            json={"action": "accepted", "actual_rate": 150000},
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_decide_recommendation_reject(self, client, manager_token, db):
        """거절 시 rejection_reason 저장"""
        from app.database.models import RateRecommendation
        import datetime

        rec = RateRecommendation(
            recommendation_date=datetime.datetime.now(),
            stay_date=date.today() + timedelta(days=6),
            recommended_rate=140000,
            current_rate=120000,
            rate_change_pct=16.7,
            reasoning="테스트",
            confidence=0.70,
            action_taken="pending",
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)

        resp = client.post(
            f"/api/v1/revenue/recommendations/{rec.id}/decide",
            json={"action": "rejected", "rejection_reason": "시장 상황 고려 불필요"},
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 200

    def test_decide_invalid_action_rejected(self, client, manager_token, db):
        """유효하지 않은 action 값 → 422"""
        from app.database.models import RateRecommendation
        import datetime

        rec = RateRecommendation(
            recommendation_date=datetime.datetime.now(),
            stay_date=date.today() + timedelta(days=7),
            recommended_rate=130000,
            current_rate=120000,
            rate_change_pct=8.3,
            reasoning="테스트",
            confidence=0.60,
            action_taken="pending",
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)

        resp = client.post(
            f"/api/v1/revenue/recommendations/{rec.id}/decide",
            json={"action": "invalid_action"},
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 422

    def test_decide_missing_rec_returns_404(self, client, manager_token):
        """존재하지 않는 ID → 404"""
        resp = client.post(
            "/api/v1/revenue/recommendations/99999/decide",
            json={"action": "accepted", "actual_rate": 120000},
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 404


class TestGroupSimulatorAPI:

    def test_simulate_returns_recommendation(self, client, manager_token):
        """POST /revenue/simulate/group — 시뮬레이션 결과 반환"""
        check_in = (date.today() + timedelta(days=10)).isoformat()
        check_out = (date.today() + timedelta(days=13)).isoformat()

        resp = client.post(
            "/api/v1/revenue/simulate/group",
            json={
                "rooms_requested": 20,
                "check_in": check_in,
                "check_out": check_out,
                "proposed_rate": 90000,
            },
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendation" in data
        assert data["recommendation"] in ("accept", "reject", "negotiate")

    def test_simulate_returns_revenue_breakdown(self, client, manager_token):
        """시뮬레이션 결과에 accept_revenue, reject_revenue 포함"""
        check_in = (date.today() + timedelta(days=15)).isoformat()
        check_out = (date.today() + timedelta(days=17)).isoformat()

        resp = client.post(
            "/api/v1/revenue/simulate/group",
            json={
                "rooms_requested": 10,
                "check_in": check_in,
                "check_out": check_out,
                "proposed_rate": 100000,
            },
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "accept_revenue" in data
        assert "reject_revenue" in data
        assert "opportunity_cost" in data
        assert "daily_breakdown" in data

    def test_simulate_invalid_dates(self, client, manager_token):
        """체크아웃 <= 체크인 → 422"""
        today = date.today().isoformat()
        resp = client.post(
            "/api/v1/revenue/simulate/group",
            json={
                "rooms_requested": 5,
                "check_in": today,
                "check_out": today,
                "proposed_rate": 80000,
            },
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 422

    def test_simulate_requires_auth(self, client):
        resp = client.post("/api/v1/revenue/simulate/group", json={})
        assert resp.status_code in (401, 403)


class TestForecastAPI:

    def test_get_forecast_range(self, client, manager_token):
        """GET /revenue/forecast — 예측 목록 반환"""
        from_d = date.today().isoformat()
        to_d = (date.today() + timedelta(days=14)).isoformat()

        resp = client.get(
            f"/api/v1/revenue/forecast?from_date={from_d}&to_date={to_d}",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_forecast_requires_auth(self, client):
        resp = client.get("/api/v1/revenue/forecast")
        assert resp.status_code in (401, 403)


class TestLocalEventsAPI:

    def test_create_local_event(self, client, manager_token):
        """POST /revenue/events — 이벤트 등록"""
        resp = client.post(
            "/api/v1/revenue/events",
            json={
                "name": "K-pop 콘서트",
                "type": "콘서트",
                "start_date": (date.today() + timedelta(days=20)).isoformat(),
                "end_date": (date.today() + timedelta(days=21)).isoformat(),
                "impact_level": "high",
            },
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_list_events(self, client, manager_token):
        """GET /revenue/events — 이벤트 목록"""
        resp = client.get(
            "/api/v1/revenue/events",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_event_requires_auth(self, client):
        resp = client.post("/api/v1/revenue/events", json={})
        assert resp.status_code in (401, 403)
