"""Compliance & Audit — Celery 태스크 TDD 테스트

Phase 1:
- generate_schedules_task: 활성 템플릿 기준 30일간 일정 자동 생성
- send_reminders_task: D-7 / D-1 알림 미발송 일정에 notify() 호출
- check_overdue_task: 어제 scheduled → overdue 상태 전환

모두 순수 Python 로직만 검증 (Celery 워커 불필요).
"""

from datetime import date, timedelta
from unittest.mock import patch, AsyncMock


# ── generate_schedules_task ─────────────────────────────────

class TestGenerateSchedulesTask:

    def test_creates_schedules_for_active_templates(self, db):
        """활성 템플릿에 대해 일정이 생성되어야 한다"""
        from app.tasks.inspection_tasks import generate_schedules_task
        from app.database.models import InspectionTemplate, InspectionSchedule

        tpl = InspectionTemplate(
            id="tpl-daily-test",
            name="일일 위생 점검",
            type="위생",
            frequency="daily",
            items=[],
            is_active=True,
        )
        db.add(tpl)
        db.commit()

        generate_schedules_task(db=db, days_ahead=3)

        schedules = db.query(InspectionSchedule).filter_by(template_id="tpl-daily-test").all()
        assert len(schedules) >= 1

    def test_skips_existing_schedules(self, db):
        """이미 존재하는 날짜는 중복 생성하지 않는다"""
        from app.tasks.inspection_tasks import generate_schedules_task
        from app.database.models import InspectionTemplate, InspectionSchedule

        tpl = InspectionTemplate(
            id="tpl-dedup-test",
            name="중복 방지 점검",
            type="안전",
            frequency="daily",
            items=[],
            is_active=True,
        )
        db.add(tpl)
        db.commit()

        generate_schedules_task(db=db, days_ahead=3)
        count_first = db.query(InspectionSchedule).filter_by(template_id="tpl-dedup-test").count()

        # 재실행해도 개수 동일
        generate_schedules_task(db=db, days_ahead=3)
        count_second = db.query(InspectionSchedule).filter_by(template_id="tpl-dedup-test").count()

        assert count_first == count_second

    def test_ignores_inactive_templates(self, db):
        """is_active=False 템플릿은 건너뜀"""
        from app.tasks.inspection_tasks import generate_schedules_task
        from app.database.models import InspectionTemplate, InspectionSchedule

        tpl = InspectionTemplate(
            id="tpl-inactive-test",
            name="비활성 점검",
            type="소방",
            frequency="daily",
            items=[],
            is_active=False,
        )
        db.add(tpl)
        db.commit()

        generate_schedules_task(db=db, days_ahead=3)

        count = db.query(InspectionSchedule).filter_by(template_id="tpl-inactive-test").count()
        assert count == 0


# ── send_reminders_task ────────────────────────────────────

class TestSendRemindersTask:

    def test_sends_7day_reminder(self, db, test_dept):
        """D-7 일정에 notify() 호출"""
        from app.tasks.inspection_tasks import send_reminders_task
        from app.database.models import (
            InspectionTemplate, InspectionSchedule, User
        )
        from app.auth.password import hash_password

        inspector = db.query(User).filter_by(email="inspector@hotel.com").first()
        if not inspector:
            inspector = User(
                email="inspector@hotel.com",
                password_hash=hash_password("pass"),
                name="점검담당자",
                role="staff",
                department_id=test_dept.id,
            )
            db.add(inspector)
            db.commit()

        tpl = InspectionTemplate(
            id="tpl-reminder-7d",
            name="위생 점검",
            type="위생",
            frequency="adhoc",
            items=[],
            is_active=True,
        )
        db.add(tpl)

        target_date = date.today() + timedelta(days=7)
        sched = InspectionSchedule(
            template_id="tpl-reminder-7d",
            scheduled_date=target_date.isoformat(),
            assigned_to=inspector.id,
            status="scheduled",
            notified_7d=False,
        )
        db.add(sched)
        db.commit()

        with patch("app.tasks.inspection_tasks.notify") as mock_notify:
            mock_notify.return_value = {"email": True}
            send_reminders_task(db=db)

        assert mock_notify.called, "D-7 알림 미발송 일정에 notify()가 호출되어야 합니다"

    def test_marks_notified_7d_flag(self, db, test_dept):
        """D-7 알림 발송 후 notified_7d=True 업데이트"""
        from app.tasks.inspection_tasks import send_reminders_task
        from app.database.models import (
            InspectionTemplate, InspectionSchedule, User
        )
        from app.auth.password import hash_password

        inspector = db.query(User).filter_by(email="inspector2@hotel.com").first()
        if not inspector:
            inspector = User(
                email="inspector2@hotel.com",
                password_hash=hash_password("pass"),
                name="점검담당자2",
                role="staff",
                department_id=test_dept.id,
            )
            db.add(inspector)
            db.commit()

        tpl = InspectionTemplate(
            id="tpl-flag-7d",
            name="소방 점검",
            type="소방",
            frequency="adhoc",
            items=[],
            is_active=True,
        )
        db.add(tpl)

        target_date = date.today() + timedelta(days=7)
        sched = InspectionSchedule(
            template_id="tpl-flag-7d",
            scheduled_date=target_date.isoformat(),
            assigned_to=inspector.id,
            status="scheduled",
            notified_7d=False,
        )
        db.add(sched)
        db.commit()
        sched_id = sched.id

        with patch("app.tasks.inspection_tasks.notify", new_callable=AsyncMock) as mock_notify:
            mock_notify.return_value = {"email": True}
            send_reminders_task(db=db)

        db.expire_all()
        updated = db.query(InspectionSchedule).filter_by(id=sched_id).first()
        assert updated.notified_7d is True

    def test_skips_already_notified(self, db, test_dept):
        """이미 notified_7d=True인 일정은 재발송하지 않는다"""
        from app.tasks.inspection_tasks import send_reminders_task
        from app.database.models import (
            InspectionTemplate, InspectionSchedule, User
        )
        from app.auth.password import hash_password

        inspector = db.query(User).filter_by(email="inspector3@hotel.com").first()
        if not inspector:
            inspector = User(
                email="inspector3@hotel.com",
                password_hash=hash_password("pass"),
                name="점검담당자3",
                role="staff",
                department_id=test_dept.id,
            )
            db.add(inspector)
            db.commit()

        tpl = InspectionTemplate(
            id="tpl-already-notified",
            name="객실 점검",
            type="객실품질",
            frequency="adhoc",
            items=[],
            is_active=True,
        )
        db.add(tpl)

        target_date = date.today() + timedelta(days=7)
        sched = InspectionSchedule(
            template_id="tpl-already-notified",
            scheduled_date=target_date.isoformat(),
            assigned_to=inspector.id,
            status="scheduled",
            notified_7d=True,  # 이미 발송됨
        )
        db.add(sched)
        db.commit()

        with patch("app.tasks.inspection_tasks.notify") as mock_notify:
            send_reminders_task(db=db)

        # notified_7d=True인 것은 호출 안 됨
        for c in mock_notify.call_args_list:
            assert "tpl-already-notified" not in str(c)


# ── check_overdue_task ─────────────────────────────────────

class TestCheckOverdueTask:

    def test_marks_past_scheduled_as_overdue(self, db):
        """어제 scheduled 상태인 일정을 overdue로 변경"""
        from app.tasks.inspection_tasks import check_overdue_task
        from app.database.models import InspectionTemplate, InspectionSchedule

        tpl = InspectionTemplate(
            id="tpl-overdue-test",
            name="지연 점검",
            type="안전",
            frequency="adhoc",
            items=[],
            is_active=True,
        )
        db.add(tpl)

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        sched = InspectionSchedule(
            template_id="tpl-overdue-test",
            scheduled_date=yesterday,
            status="scheduled",
        )
        db.add(sched)
        db.commit()
        sched_id = sched.id

        with patch("app.tasks.inspection_tasks.notify", new_callable=AsyncMock):
            check_overdue_task(db=db)

        db.expire_all()
        updated = db.query(InspectionSchedule).filter_by(id=sched_id).first()
        assert updated.status == "overdue"

    def test_completed_not_marked_overdue(self, db):
        """completed 상태는 overdue로 변경하지 않음"""
        from app.tasks.inspection_tasks import check_overdue_task
        from app.database.models import InspectionTemplate, InspectionSchedule

        tpl = InspectionTemplate(
            id="tpl-completed-test",
            name="완료 점검",
            type="위생",
            frequency="adhoc",
            items=[],
            is_active=True,
        )
        db.add(tpl)

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        sched = InspectionSchedule(
            template_id="tpl-completed-test",
            scheduled_date=yesterday,
            status="completed",
        )
        db.add(sched)
        db.commit()
        sched_id = sched.id

        with patch("app.tasks.inspection_tasks.notify", new_callable=AsyncMock):
            check_overdue_task(db=db)

        db.expire_all()
        updated = db.query(InspectionSchedule).filter_by(id=sched_id).first()
        assert updated.status == "completed"


# ── 기본 템플릿 시드 데이터 ──────────────────────────────────

class TestInspectionTemplateSeedData:

    def test_seed_creates_default_templates(self, db):
        """seed_inspection_templates()가 기본 4종 템플릿을 생성한다"""
        from app.tasks.inspection_tasks import seed_inspection_templates
        from app.database.models import InspectionTemplate

        seed_inspection_templates(db=db)

        templates = db.query(InspectionTemplate).all()
        types = {t.type for t in templates}

        assert "위생" in types
        assert "소방" in types
        assert "안전" in types
        assert "객실품질" in types

    def test_seed_is_idempotent(self, db):
        """여러 번 호출해도 중복 생성 안 됨"""
        from app.tasks.inspection_tasks import seed_inspection_templates
        from app.database.models import InspectionTemplate

        seed_inspection_templates(db=db)
        count_first = db.query(InspectionTemplate).count()

        seed_inspection_templates(db=db)
        count_second = db.query(InspectionTemplate).count()

        assert count_first == count_second
