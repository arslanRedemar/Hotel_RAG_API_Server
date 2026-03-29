"""Web Push 알림 (VAPID / pywebpush)"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_push(
    subscription_info: dict,
    title: str,
    body: str,
    url: str = "/",
    icon: str = "/icon-192.png",
) -> bool:
    """
    subscription_info 예시:
      {"endpoint": "...", "keys": {"p256dh": "...", "auth": "..."}}
    """
    if not settings.vapid_private_key or not settings.vapid_public_key:
        logger.warning("VAPID 미설정 — Push 발송 건너뜀")
        return False

    try:
        from pywebpush import webpush
        import json

        payload = json.dumps({"title": title, "body": body, "url": url, "icon": icon})

        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": f"mailto:{settings.smtp_user or 'admin@hotel.local'}"},
        )
        logger.info("Push 발송 완료", extra={"endpoint": subscription_info.get("endpoint", "")[:40]})
        return True
    except Exception as exc:
        logger.error("Push 발송 실패", extra={"error": str(exc)})
        return False
