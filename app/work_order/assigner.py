"""Work Order 자동 배정 엔진 (WO-F20, F21, F22, F23)"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── SLA 설정 ─────────────────────────────────────────────────

@dataclass
class SLAConfig:
    assign_limit_min: int
    complete_limit_min: int
    escalate_at_min: int

    @classmethod
    def for_severity(cls, severity: str) -> "SLAConfig":
        _MAP = {
            "critical": cls(assign_limit_min=5,   complete_limit_min=120,  escalate_at_min=5),
            "high":     cls(assign_limit_min=15,  complete_limit_min=240,  escalate_at_min=15),
            "medium":   cls(assign_limit_min=60,  complete_limit_min=480,  escalate_at_min=120),
            "low":      cls(assign_limit_min=240, complete_limit_min=4320, escalate_at_min=480),
        }
        if severity not in _MAP:
            raise ValueError(f"유효하지 않은 긴급도: {severity}")
        return _MAP[severity]


# ── 자동 배정 엔진 ────────────────────────────────────────────

class AutoAssigner:
    def __init__(self, db=None):
        self.db = db

    # ── 공개 메서드 ──────────────────────────────────────────

    def assign(self, wo_id: str, category: str, severity: str) -> dict | None:
        """WO-F20: 가용한 담당자를 찾아 배정"""
        candidates = self._get_candidates(category)
        available = [c for c in candidates if getattr(getattr(c, "capability", None), "is_available", True)]
        if not available:
            logger.warning("wo_id=%s: 가용 담당자 없음 (category=%s)", wo_id, category)
            return None

        assignee = available[0]
        self._notify_assignee(assignee, wo_id, severity)
        return {"assigned_to": assignee.id, "assigned_at": datetime.now(timezone.utc).isoformat()}

    def handle_rejection(self, wo_id: str, rejected_by: int) -> dict | None:
        """WO-F21: 거절 → 다음 담당자 재배정"""
        next_candidate = self._get_next_candidate(wo_id, excluded_user_id=rejected_by)
        if next_candidate is None:
            self._escalate_to_manager(wo_id, reason="모든 담당자 거절")
            return None
        self._notify_assignee(next_candidate, wo_id, severity="medium")
        return {"assigned_to": next_candidate.id, "assigned_at": datetime.now(timezone.utc).isoformat()}

    def check_sla_and_escalate(self, wo) -> None:
        """WO-F22: SLA 초과 여부 확인 후 에스컬레이션"""
        if wo.status in ("completed", "cancelled"):
            return

        now = datetime.now(timezone.utc)
        deadline_str = wo.sla_deadline
        if not deadline_str:
            return

        if isinstance(deadline_str, str):
            deadline = datetime.fromisoformat(deadline_str)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
        else:
            deadline = deadline_str

        if now > deadline:
            self._escalate_to_manager(wo.id if hasattr(wo, "id") else str(wo), reason="SLA 기한 초과")

    def assign_external_vendor(
        self, wo_id: str, vendor_name: str, vendor_contact: str, changed_by: int
    ) -> dict:
        """WO-F23: 외부 업체 정보 기록"""
        return {
            "wo_id": wo_id,
            "external_vendor": vendor_name,
            "external_contact": vendor_contact,
            "changed_by": changed_by,
            "changed_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── 내부 메서드 ──────────────────────────────────────────

    def _get_candidates(self, category: str) -> list:
        """DB에서 해당 카테고리 담당 가능한 사용자 목록 조회"""
        if self.db is None:
            return []
        try:
            from app.database.models import AssigneeCapability, User
            rows = (
                self.db.query(User)
                .join(AssigneeCapability, User.id == AssigneeCapability.user_id)
                .filter(AssigneeCapability.category == category)
                .order_by(AssigneeCapability.priority)
                .all()
            )
            return rows
        except Exception as exc:
            logger.warning("담당자 조회 실패: %s", exc)
            return []

    def _get_next_candidate(self, wo_id: str, excluded_user_id: int) -> object | None:
        return None

    def _notify_assignee(self, assignee, wo_id: str, severity: str) -> None:
        logger.info("배정 알림 발송: user=%s, wo_id=%s, severity=%s", assignee.id, wo_id, severity)

    def _escalate_to_manager(self, wo_id: str, reason: str) -> None:
        logger.warning("에스컬레이션: wo_id=%s, reason=%s", wo_id, reason)
