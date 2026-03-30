"""불변 감사 로그 기록기 — INSERT/SELECT만 허용 (DELETE 없음)"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def archive_old_logs(db, older_than_years: int = 5, archive_dir: str | None = None) -> int:
    """5년 이상 된 감사 로그를 JSON Lines 파일로 내보내기 (불변 보존).

    DB 레코드는 삭제하지 않으며 아카이브 파일에 복사 저장합니다.
    Returns:
        처리된 로그 수 (아카이브 대상이 없으면 0)
    """
    from app.core.config import settings

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_years * 365)
    old_logs = db.query(AuditLog).filter(AuditLog.occurred_at < cutoff).all()
    if not old_logs:
        return 0

    base_dir = Path(archive_dir or settings.file_storage_path) / "audit_archive"
    base_dir.mkdir(parents=True, exist_ok=True)
    archive_file = base_dir / f"audit_{cutoff.strftime('%Y%m%d')}.jsonl"

    with archive_file.open("a", encoding="utf-8") as fp:
        for log in old_logs:
            fp.write(
                json.dumps(
                    {
                        "id": log.id,
                        "action": log.action,
                        "entity_type": log.entity_type,
                        "entity_id": log.entity_id,
                        "actor_id": log.actor_id,
                        "actor_email": log.actor_email,
                        "ip_address": log.ip_address,
                        "before_value": log.before_value,
                        "after_value": log.after_value,
                        "occurred_at": log.occurred_at.isoformat() if log.occurred_at else None,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    _log.info("감사 로그 아카이빙 완료: %d건 → %s", len(old_logs), archive_file)
    return len(old_logs)
