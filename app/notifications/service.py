"""알림 통합 서비스 — 채널별 발송 조율"""

import logging
from enum import Enum

from app.notifications.email import send_email
from app.notifications.push import send_push

logger = logging.getLogger(__name__)


class NotificationChannel(str, Enum):
    EMAIL = "email"
    PUSH = "push"
    ALL = "all"


async def notify(
    *,
    channel: NotificationChannel = NotificationChannel.ALL,
    # Email 파라미터
    email_to: str | list[str] | None = None,
    subject: str = "",
    body_html: str = "",
    body_text: str = "",
    # Push 파라미터
    subscriptions: list[dict] | None = None,
    push_title: str = "",
    push_body: str = "",
    push_url: str = "/",
) -> dict[str, bool]:
    results: dict[str, bool] = {}

    if channel in (NotificationChannel.EMAIL, NotificationChannel.ALL):
        if email_to and subject and body_html:
            results["email"] = await send_email(email_to, subject, body_html, body_text)

    if channel in (NotificationChannel.PUSH, NotificationChannel.ALL):
        if subscriptions and push_title:
            push_results = []
            for sub in subscriptions:
                ok = send_push(sub, push_title, push_body, push_url)
                push_results.append(ok)
            results["push"] = any(push_results)

    return results
