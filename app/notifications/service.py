"""알림 통합 서비스 — 채널별 발송 조율 + SYS-F12 이력 저장"""

import logging
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationChannel(str, Enum):
    EMAIL = "email"
    PUSH = "push"
    ALL = "all"


async def notify(
    *,
    channel: str | NotificationChannel = NotificationChannel.ALL,
    # 단순화된 파라미터 (SYS-F12 이력 저장 지원)
    recipient: str | list[str] | dict | None = None,
    subject: str = "",
    body: str = "",
    user_id: Optional[int] = None,
    db=None,
    # 기존 파라미터 (하위 호환)
    email_to: str | list[str] | None = None,
    body_html: str = "",
    body_text: str = "",
    subscriptions: list[dict] | None = None,
    push_title: str = "",
    push_body: str = "",
    push_url: str = "/",
) -> dict[str, bool]:
    results: dict[str, bool] = {}
    channel_str = channel.value if isinstance(channel, NotificationChannel) else channel

    # recipient 우선 처리
    if recipient is not None:
        if channel_str == "email" and isinstance(recipient, str):
            email_to = recipient
            body_html = body_html or body
        elif channel_str == "push" and isinstance(recipient, dict):
            subscriptions = [recipient]
            push_title = push_title or subject
            push_body = push_body or body

    if channel_str in ("email", "all"):
        if email_to and subject:
            from app.notifications.email import send_email  # noqa: PLC0415
            ok = await send_email(email_to, subject, body_html or body, body_text)
            results["email"] = ok
            if db is not None:
                _save_log(
                    db=db,
                    channel="email",
                    subject=subject,
                    body=body_html or body,
                    user_id=user_id,
                    recipient_email=email_to if isinstance(email_to, str) else str(email_to),
                    status="sent" if ok else "failed",
                )

    if channel_str in ("push", "all"):
        if subscriptions and (push_title or subject):
            from app.notifications.push import send_push  # noqa: PLC0415
            push_results = []
            for sub in subscriptions:
                ok = send_push(sub, push_title or subject, push_body or body, push_url)
                push_results.append(ok)
            results["push"] = any(push_results)
            if db is not None:
                _save_log(
                    db=db,
                    channel="push",
                    subject=push_title or subject,
                    body=push_body or body,
                    user_id=user_id,
                    status="sent" if results.get("push") else "failed",
                )

    return results


def _save_log(
    db,
    channel: str,
    subject: str,
    body: str,
    status: str,
    user_id: Optional[int] = None,
    recipient_email: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """SYS-F12: 알림 발송 이력을 DB에 저장"""
    try:
        from app.database.models import NotificationLog
        log = NotificationLog(
            user_id=user_id,
            channel=channel,
            subject=subject,
            body=body,
            recipient_email=recipient_email,
            status=status,
            error_message=error_message,
            sent_at=datetime.utcnow() if status == "sent" else None,
        )
        db.add(log)
        db.commit()
    except Exception as exc:
        logger.warning("알림 이력 저장 실패: %s", exc)
