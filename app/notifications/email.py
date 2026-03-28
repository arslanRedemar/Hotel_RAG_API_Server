"""SMTP 이메일 발송 (aiosmtplib 비동기)"""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_email(
    to: str | list[str],
    subject: str,
    body_html: str,
    body_text: str = "",
) -> bool:
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP 미설정 — 이메일 발송 건너뜀")
        return False

    recipients = [to] if isinstance(to, str) else to

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_user
    msg["To"] = ", ".join(recipients)

    if body_text:
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=True,
        )
        logger.info("이메일 발송 완료", extra={"to": recipients, "subject": subject})
        return True
    except Exception as exc:
        logger.error("이메일 발송 실패", extra={"error": str(exc), "to": recipients})
        return False
