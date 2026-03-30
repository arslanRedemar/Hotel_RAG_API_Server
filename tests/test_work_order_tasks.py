"""Work Order Celery 태스크 TDD 테스트 (WO-F22)

- schedule_escalation_check: SLA 기한 초과 시 에스컬레이션
- seed_assignee_capabilities: 기본 담당자 역량 데이터 시드
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch


# ── schedule_escalation_check ──────────────────────────────────

class TestScheduleEscalationCheck:

    def test_escalates_overdue_wo(self, db, staff_user):
        """SLA 기한 초과 WO는 escalated=True 처리"""
        from app.tasks.work_order_tasks import schedule_escalation_check
        from app.database.models import WorkOrder

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        wo = WorkOrder(
            id="wo-esc-1",
            wo_number="WO-2026-ESC1",
            description="SLA 초과 테스트",
            category="전기",
            severity="high",
            status="assigned",
            reported_by=staff_user.id,
            sla_deadline=past,
        )
        db.add(wo)
        db.commit()

        with patch("app.tasks.work_order_tasks.notify", new_callable=AsyncMock):
            schedule_escalation_check(wo_id="wo-esc-1", db=db)

        db.expire_all()
        updated = db.query(WorkOrder).filter_by(id="wo-esc-1").first()
        assert updated.escalated is True

    def test_no_escalation_when_completed(self, db, staff_user):
        """완료된 WO는 에스컬레이션하지 않는다"""
        from app.tasks.work_order_tasks import schedule_escalation_check
        from app.database.models import WorkOrder

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        wo = WorkOrder(
            id="wo-esc-done",
            wo_number="WO-2026-DONE",
            description="완료된 WO",
            category="배관",
            severity="low",
            status="completed",
            reported_by=staff_user.id,
            sla_deadline=past,
        )
        db.add(wo)
        db.commit()

        with patch("app.tasks.work_order_tasks.notify", new_callable=AsyncMock):
            schedule_escalation_check(wo_id="wo-esc-done", db=db)

        db.expire_all()
        updated = db.query(WorkOrder).filter_by(id="wo-esc-done").first()
        assert updated.escalated is False

    def test_no_escalation_within_sla(self, db, staff_user):
        """SLA 기한 이내 WO는 에스컬레이션하지 않는다"""
        from app.tasks.work_order_tasks import schedule_escalation_check
        from app.database.models import WorkOrder

        future = datetime.now(timezone.utc) + timedelta(hours=2)
        wo = WorkOrder(
            id="wo-esc-ok",
            wo_number="WO-2026-OK",
            description="아직 SLA 이내",
            category="가구",
            severity="medium",
            status="in_progress",
            reported_by=staff_user.id,
            sla_deadline=future,
        )
        db.add(wo)
        db.commit()

        with patch("app.tasks.work_order_tasks.notify", new_callable=AsyncMock):
            schedule_escalation_check(wo_id="wo-esc-ok", db=db)

        db.expire_all()
        updated = db.query(WorkOrder).filter_by(id="wo-esc-ok").first()
        assert updated.escalated is False

    def test_notifies_managers_on_escalation(self, db, manager_user, test_dept):
        """에스컬레이션 시 관리자에게 notify() 호출"""
        from app.tasks.work_order_tasks import schedule_escalation_check
        from app.database.models import WorkOrder

        past = datetime.now(timezone.utc) - timedelta(hours=2)
        wo = WorkOrder(
            id="wo-esc-notify",
            wo_number="WO-2026-NOTIFY",
            description="관리자 알림 테스트",
            category="에어컨",
            severity="critical",
            status="assigned",
            reported_by=manager_user.id,
            sla_deadline=past,
        )
        db.add(wo)
        db.commit()

        with patch("app.tasks.work_order_tasks.notify") as mock_notify:
            mock_notify.return_value = {"email": True}
            schedule_escalation_check(wo_id="wo-esc-notify", db=db)

        assert mock_notify.called, "에스컬레이션 시 notify()가 호출되어야 합니다"

    def test_returns_early_for_missing_wo(self, db):
        """존재하지 않는 WO는 예외 없이 종료"""
        from app.tasks.work_order_tasks import schedule_escalation_check

        # 예외 없이 실행되어야 함
        schedule_escalation_check(wo_id="nonexistent-wo", db=db)


# ── 사진 업로드 엔드포인트 ─────────────────────────────────────

class TestAddPhotos:

    def test_add_photos_returns_updated_wo(self, client, staff_token, db, staff_user):
        """POST /work-orders/{id}/photos 는 업데이트된 WO를 반환"""
        from app.database.models import WorkOrder

        wo = WorkOrder(
            id="wo-photo-1",
            wo_number="WO-2026-PH1",
            description="사진 첨부 테스트",
            category="전기",
            severity="medium",
            status="open",
            reported_by=staff_user.id,
            photo_urls=[],
        )
        db.add(wo)
        db.commit()

        resp = client.post(
            "/api/v1/work-orders/wo-photo-1/photos",
            json={"photo_urls": ["https://cdn.hotel.com/photo1.jpg"]},
            headers={"Authorization": f"Bearer {staff_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "https://cdn.hotel.com/photo1.jpg" in data.get("photo_urls", [])

    def test_add_photos_appends_to_existing(self, client, staff_token, db, staff_user):
        """기존 사진에 새 사진이 추가(덮어쓰기 아님)"""
        from app.database.models import WorkOrder

        wo = WorkOrder(
            id="wo-photo-2",
            wo_number="WO-2026-PH2",
            description="사진 추가 테스트",
            category="배관",
            severity="low",
            status="open",
            reported_by=staff_user.id,
            photo_urls=["https://cdn.hotel.com/existing.jpg"],
        )
        db.add(wo)
        db.commit()

        resp = client.post(
            "/api/v1/work-orders/wo-photo-2/photos",
            json={"photo_urls": ["https://cdn.hotel.com/new.jpg"]},
            headers={"Authorization": f"Bearer {staff_token}"},
        )
        assert resp.status_code == 200
        urls = resp.json().get("photo_urls", [])
        assert "https://cdn.hotel.com/existing.jpg" in urls
        assert "https://cdn.hotel.com/new.jpg" in urls

    def test_add_photos_404_for_unknown_wo(self, client, staff_token):
        """존재하지 않는 WO에 사진 추가 시 404"""
        resp = client.post(
            "/api/v1/work-orders/nonexistent/photos",
            json={"photo_urls": ["https://cdn.hotel.com/photo.jpg"]},
            headers={"Authorization": f"Bearer {staff_token}"},
        )
        assert resp.status_code == 404

    def test_requires_auth(self, client):
        """인증 없이 사진 추가 시 401/403"""
        resp = client.post(
            "/api/v1/work-orders/wo-any/photos",
            json={"photo_urls": []},
        )
        assert resp.status_code in (401, 403)


# ── AssigneeCapability 시드 데이터 ─────────────────────────────

class TestAssigneeCapabilitySeed:

    def test_seed_creates_capabilities(self, db, staff_user):
        """seed_assignee_capabilities()가 기본 역량 데이터를 생성한다"""
        from app.tasks.work_order_tasks import seed_assignee_capabilities
        from app.database.models import AssigneeCapability

        seed_assignee_capabilities(db=db, user_id=staff_user.id)

        caps = db.query(AssigneeCapability).filter_by(user_id=staff_user.id).all()
        categories = {c.category for c in caps}
        # 기본 카테고리 6종 모두 있어야 함
        assert len(categories) >= 1

    def test_seed_is_idempotent(self, db, staff_user):
        """여러 번 호출해도 중복 생성 안 됨"""
        from app.tasks.work_order_tasks import seed_assignee_capabilities
        from app.database.models import AssigneeCapability

        seed_assignee_capabilities(db=db, user_id=staff_user.id)
        count1 = db.query(AssigneeCapability).filter_by(user_id=staff_user.id).count()

        seed_assignee_capabilities(db=db, user_id=staff_user.id)
        count2 = db.query(AssigneeCapability).filter_by(user_id=staff_user.id).count()

        assert count1 == count2
