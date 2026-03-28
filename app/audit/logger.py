"""불변 감사 로그 기록기 — INSERT/SELECT만 허용 (DELETE 없음)"""

import logging
from datetime import datetime, timezone

from app.database.connection import get_audit_db
from app.database.models import AuditLog

_log = logging.getLogger("audit")


class AuditLogger:
    def log(
        self,
        action: str,
        entity_type: str,
        entity_id: str | int | None = None,
        actor_id: int | None = None,
        actor_email: str | None = None,
        ip_address: str | None = None,
        before_value: dict | None = None,
        after_value: dict | None = None,
        metadata: dict | None = None,
    ) -> None:
        entry = AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            actor_id=actor_id,
            actor_email=actor_email,
            ip_address=ip_address,
            before_value=before_value,
            after_value=after_value,
            metadata_=metadata,
            occurred_at=datetime.now(timezone.utc),
        )

        try:
            with get_audit_db() as db:
                db.add(entry)
                db.commit()
        except Exception as exc:
            # DB 저장 실패 시 파일 로그에 백업 (감사 로그 유실 방지)
            _log.error(
                "감사 로그 DB 저장 실패",
                extra={
                    "action": action,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "error": str(exc),
                },
            )


audit_log = AuditLogger()
