"""SYS-F12: 알림 발송 이력 DB 저장 테스트"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.database.models import Department, User
from app.auth.password import hash_password


# ── 픽스처 ────────────────────────────────────────────────────

@pytest.fixture
def notif_dept(db):
    dept = db.query(Department).filter_by(code="NOTIF_TEST").first()
    if not dept:
        dept = Department(name="알림테스트부서", code="NOTIF_TEST")
        db.add(dept)
        db.commit()
        db.refresh(dept)
    return dept


@pytest.fixture
def notif_user(db, notif_dept):
    user = db.query(User).filter_by(email="notif@hotel.local").first()
    if not user:
        user = User(
            email="notif@hotel.local",
            password_hash=hash_password("Notif1234!"),
            name="알림수신자",
            role="staff",
            department_id=notif_dept.id,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ── 단위 테스트: NotificationLog 모델 ───────────────────────

class TestNotificationLogModel:
    def test_create_notification_log(self, db, notif_user):
        """NotificationLog 생성 및 저장"""
        from app.database.models import NotificationLog
        log = NotificationLog(
            user_id=notif_user.id,
            channel="email",
            subject="테스트 알림",
            body="알림 내용",
            status="sent",
            sent_at=datetime.utcnow(),
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        assert log.id is not None
        assert log.channel == "email"
        assert log.status == "sent"

    def test_notification_log_failed_status(self, db, notif_user):
        """발송 실패 기록"""
        from app.database.models import NotificationLog
        log = NotificationLog(
            user_id=notif_user.id,
            channel="push",
            subject="푸시 테스트",
            body="내용",
            status="failed",
            error_message="VAPID 키 없음",
        )
        db.add(log)
        db.commit()
        assert log.status == "failed"
        assert log.error_message is not None

    def test_notification_log_nullable_user(self, db):
        """user_id 없이도 저장 가능 (시스템 알림)"""
        from app.database.models import NotificationLog
        log = NotificationLog(
            user_id=None,
            channel="email",
            subject="시스템 알림",
            body="내용",
            status="sent",
            recipient_email="ops@hotel.local",
        )
        db.add(log)
        db.commit()
        assert log.id is not None


# ── 단위 테스트: 알림 서비스 이력 저장 ──────────────────────

class TestNotificationServiceLogging:
    def test_email_success_logged(self, db, notif_user):
        """이메일 성공 시 DB에 이력 저장"""
        from app.notifications.service import notify
        from app.database.models import NotificationLog

        with patch("app.notifications.email.send_email", new_callable=AsyncMock, return_value=True):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                notify(
                    db=db,
                    channel="email",
                    recipient=notif_user.email,
                    subject="점검 알림",
                    body="내일 점검 예정입니다",
                    user_id=notif_user.id,
                )
            )

        logs = db.query(NotificationLog).filter_by(user_id=notif_user.id, channel="email").all()
        assert len(logs) >= 1
        assert logs[-1].status == "sent"
        assert logs[-1].subject == "점검 알림"

    def test_email_failure_logged(self, db, notif_user):
        """이메일 실패 시 failed 상태로 이력 저장"""
        from app.notifications.service import notify
        from app.database.models import NotificationLog

        with patch("app.notifications.email.send_email", new_callable=AsyncMock, return_value=False):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                notify(
                    db=db,
                    channel="email",
                    recipient=notif_user.email,
                    subject="실패 알림",
                    body="내용",
                    user_id=notif_user.id,
                )
            )

        logs = db.query(NotificationLog).filter_by(user_id=notif_user.id, subject="실패 알림").all()
        assert len(logs) >= 1
        assert logs[-1].status == "failed"

    def test_push_success_logged(self, db, notif_user):
        """푸시 성공 시 이력 저장"""
        from app.notifications.service import notify
        from app.database.models import NotificationLog

        with patch("app.notifications.push.send_push", return_value=True):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                notify(
                    db=db,
                    channel="push",
                    recipient={"endpoint": "https://push.example.com", "p256dh": "key", "auth": "auth"},
                    subject="푸시 알림",
                    body="내용",
                    user_id=notif_user.id,
                )
            )

        logs = db.query(NotificationLog).filter_by(user_id=notif_user.id, channel="push").all()
        assert len(logs) >= 1
        assert logs[-1].status == "sent"


# ── 통합 테스트: 로그 조회 API ───────────────────────────────

class TestNotificationLogAPI:
    @pytest.fixture
    def admin_user(self, db, notif_dept):
        user = db.query(User).filter_by(email="notif_admin@hotel.local").first()
        if not user:
            user = User(
                email="notif_admin@hotel.local",
                password_hash=hash_password("Admin1234!"),
                name="알림관리자",
                role="admin",
                department_id=notif_dept.id,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    @pytest.fixture
    def admin_token(self, client, admin_user):
        r = client.post("/api/v1/auth/login", json={
            "email": "notif_admin@hotel.local",
            "password": "Admin1234!",
        })
        return r.json()["access_token"]

    def test_get_notification_logs(self, client, db, notif_user, admin_token):
        """관리자는 알림 로그 목록 조회 가능"""
        from app.database.models import NotificationLog
        log = NotificationLog(
            user_id=notif_user.id,
            channel="email",
            subject="조회 테스트 알림",
            body="내용",
            status="sent",
            sent_at=datetime.utcnow(),
        )
        db.add(log)
        db.commit()

        r = client.get(
            "/api/v1/admin/notification-logs",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert any(entry["subject"] == "조회 테스트 알림" for entry in data)

    def test_notification_logs_require_admin(self, client):
        """비인증 요청은 401"""
        r = client.get("/api/v1/admin/notification-logs")
        assert r.status_code in (401, 403)
