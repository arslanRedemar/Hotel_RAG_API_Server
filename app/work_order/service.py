"""Work Order 서비스 레이어 (WO-F01, F13, F30, F31, F40~F42)"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.work_order.assigner import AutoAssigner, SLAConfig
from app.work_order.classifier import WorkOrderClassifier
from app.work_order.pattern_analyzer import PatternAnalyzer

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"전기", "에어컨", "배관", "가구", "청결", "기타"}
VALID_STATUSES = {"open", "assigned", "in_progress", "on_hold", "completed", "cancelled"}

# 허용되는 상태 전환 맵
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open":        {"assigned", "in_progress", "on_hold", "cancelled"},
    "assigned":    {"in_progress", "on_hold", "cancelled"},
    "in_progress": {"completed", "on_hold", "cancelled"},
    "on_hold":     {"in_progress", "cancelled"},
    "completed":   set(),
    "cancelled":   set(),
}

_WO_COUNTER: dict[str, int] = {}  # 연도별 카운터 (인메모리, 프로덕션은 DB 시퀀스 사용)


def save_wo_history(db, wo_id: str, status: str, changed_by: int | None, note: str | None = None):
    """WO 이력 DB 저장 헬퍼"""
    try:
        from app.database.models import WorkOrderHistory
        entry = WorkOrderHistory(
            wo_id=wo_id,
            status=status,
            changed_by=changed_by,
            changed_at=datetime.utcnow(),
            note=note,
        )
        db.add(entry)
        db.flush()
    except Exception as exc:
        logger.warning("이력 저장 실패: %s", exc)


class WorkOrderService:
    def __init__(self, db=None):
        self.db = db
        self.classifier = WorkOrderClassifier()
        self.notifier = None  # 주입 가능

    # ── WO-F01: 생성 ─────────────────────────────────────────

    def create_work_order(
        self,
        description: str,
        reported_by: int,
        room_no: str | None = None,
        category: str | None = None,
        severity: str | None = None,
        location: str | None = None,
        photo_urls: list | None = None,
    ) -> dict:
        classification = self.classifier.classify(description)

        final_category = category or classification.category
        final_severity = severity or classification.severity

        sla = SLAConfig.for_severity(final_severity)
        now = datetime.now(timezone.utc)
        sla_deadline = (now + timedelta(minutes=sla.complete_limit_min)).isoformat()

        wo_number = self._generate_wo_number()
        wo_id = str(uuid.uuid4())

        history = [
            self.build_history_entry(status="접수", changed_by=reported_by, note=None)
        ]

        wo = {
            "id": wo_id,
            "wo_number": wo_number,
            "room_no": room_no,
            "location": location,
            "category": final_category,
            "description": description,
            "photo_urls": photo_urls or [],
            "ai_category": classification.category,
            "ai_severity": classification.severity,
            "severity": final_severity,
            "status": "open",
            "reported_by": reported_by,
            "reported_at": now.isoformat(),
            "assigned_to": None,
            "sla_deadline": sla_deadline,
            "history": history,
            "parts_used": [],
            "resolution_note": None,
            "actual_duration_min": None,
            "external_vendor": None,
            "escalated": False,
            "ai_classification": {
                "category": classification.category,
                "severity": classification.severity,
                "confidence": classification.confidence,
                "reasoning": classification.reasoning,
            },
        }

        # DB 저장
        if self.db:
            self._persist_wo(wo)

        # 자동 배정
        assigner = AutoAssigner(db=self.db)
        assignment = assigner.assign(
            wo_id=wo_id, category=final_category, severity=final_severity
        )
        if assignment:
            wo["assigned_to"] = assignment["assigned_to"]
            wo["assigned_at"] = assignment["assigned_at"]
            wo["status"] = "assigned"
            wo["history"].append(
                self.build_history_entry(
                    status="배정",
                    changed_by=None,
                    note=f"자동 배정: user_id={assignment['assigned_to']}",
                )
            )

        return wo

    # ── WO-F13: 카테고리 수정 ────────────────────────────────

    def update_category(self, wo_id: str, new_category: str, changed_by: int) -> dict:
        if new_category not in VALID_CATEGORIES:
            raise ValueError(f"유효하지 않은 카테고리: {new_category}")

        if self.db:
            from app.database.models import WorkOrder
            wo = self.db.query(WorkOrder).filter(WorkOrder.id == wo_id).first()
            if wo:
                old = wo.category
                wo.category = new_category
                self.db.flush()
                save_wo_history(
                    self.db, wo_id, f"카테고리 변경: {old}→{new_category}", changed_by
                )
                return {"id": wo_id, "category": new_category}
        return {"id": wo_id, "category": new_category}

    # ── WO-F30: 상태 전환 검증 ──────────────────────────────

    def is_valid_transition(self, from_status: str, to_status: str) -> bool:
        return to_status in _ALLOWED_TRANSITIONS.get(from_status, set())

    def update_status(
        self, wo_id: str, new_status: str, changed_by: int, note: str | None = None
    ) -> dict:
        if new_status not in VALID_STATUSES:
            raise ValueError(f"유효하지 않은 상태: {new_status}")

        if self.db:
            from app.database.models import WorkOrder
            wo = self.db.query(WorkOrder).filter(WorkOrder.id == wo_id).first()
            if not wo:
                raise ValueError(f"Work Order 없음: {wo_id}")
            if not self.is_valid_transition(wo.status, new_status):
                raise ValueError(f"유효하지 않은 상태 전환: {wo.status} → {new_status}")
            wo.status = new_status
            save_wo_history(self.db, wo_id, new_status, changed_by, note)
            self.db.flush()
            return self._wo_to_dict(wo)

        # DB 없는 경우 (테스트 목적)
        raise ValueError("DB 없음")

    # ── WO-F31: 완료 처리 검증 ──────────────────────────────

    def validate_completion_data(
        self,
        resolution_note: str | None,
        actual_duration_min: int | None,
        parts_used: list | None,
    ) -> None:
        if not resolution_note:
            raise ValueError("resolution_note 필수입니다")
        if actual_duration_min is None:
            raise ValueError("actual_duration_min 필수입니다")
        if actual_duration_min < 0:
            raise ValueError("actual_duration_min은 0 이상이어야 합니다")

    def complete_work_order(
        self,
        wo_id: str,
        resolution_note: str,
        actual_duration_min: int,
        parts_used: list,
        changed_by: int,
    ) -> dict:
        self.validate_completion_data(resolution_note, actual_duration_min, parts_used)

        if self.db:
            from app.database.models import WorkOrder
            wo = self.db.query(WorkOrder).filter(WorkOrder.id == wo_id).first()
            if not wo:
                raise ValueError(f"Work Order 없음: {wo_id}")
            wo.status = "completed"
            wo.resolution_note = resolution_note
            wo.actual_duration_min = actual_duration_min
            wo.parts_used = parts_used
            wo.completed_at = datetime.utcnow()
            save_wo_history(self.db, wo_id, "completed", changed_by, resolution_note)
            self.db.flush()
            return self._wo_to_dict(wo)

        raise ValueError("DB 없음")

    # ── WO-F40: 이력 엔트리 빌더 ────────────────────────────

    def build_history_entry(
        self, status: str, changed_by: int | None, note: str | None = None
    ) -> dict:
        return {
            "status": status,
            "changed_by": changed_by,
            "changed_at": datetime.now(timezone.utc).isoformat(),
            "note": note,
        }

    # ── WO-F41: 통계 ────────────────────────────────────────

    def get_stats(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        severity: str | None = None,
        category: str | None = None,
    ) -> dict:
        if not self.db:
            return {}
        from app.database.models import WorkOrder
        from sqlalchemy import func

        q = self.db.query(WorkOrder)
        if severity:
            q = q.filter(WorkOrder.severity == severity)
        if category:
            q = q.filter(WorkOrder.category == category)

        rows = q.all()
        total = len(rows)

        by_severity: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_category: dict[str, int] = {}
        durations = []
        sla_breach = 0

        for wo in rows:
            by_severity[wo.severity] = by_severity.get(wo.severity, 0) + 1
            by_status[wo.status] = by_status.get(wo.status, 0) + 1
            by_category[wo.category] = by_category.get(wo.category, 0) + 1
            if wo.actual_duration_min is not None:
                durations.append(wo.actual_duration_min)
            if wo.escalated:
                sla_breach += 1

        avg = sum(durations) / len(durations) if durations else 0.0

        return {
            "total": total,
            "by_severity": by_severity,
            "by_status": by_status,
            "by_category": by_category,
            "avg_completion_min": round(avg, 1),
            "sla_breach_count": sla_breach,
        }

    # ── WO-F42: 주간 KPI ────────────────────────────────────

    def get_weekly_kpi(self) -> dict:
        stats = self.get_stats()
        total = stats.get("total", 0)
        breach = stats.get("sla_breach_count", 0)
        compliance = round((total - breach) / total, 4) if total > 0 else 1.0

        pattern_analyzer = PatternAnalyzer()
        wos_raw = self._get_all_wo_dicts()
        patterns = pattern_analyzer.analyze(wos_raw, window_days=7, min_count=2)

        return {
            "avg_completion_min": stats.get("avg_completion_min", 0.0),
            "sla_compliance_rate": compliance,
            "escalation_count": breach,
            "repeat_fault_top5": patterns[:5],
            "total_work_orders": total,
        }

    # ── 목록 조회 ────────────────────────────────────────────

    def list_work_orders(
        self,
        status: str | None = None,
        severity: str | None = None,
        assigned_to: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        if not self.db:
            return []
        from app.database.models import WorkOrder
        q = self.db.query(WorkOrder)
        if status:
            q = q.filter(WorkOrder.status == status)
        if severity:
            q = q.filter(WorkOrder.severity == severity)
        if assigned_to:
            q = q.filter(WorkOrder.assigned_to == assigned_to)
        rows = q.order_by(WorkOrder.reported_at.desc()).offset(offset).limit(limit).all()
        return [self._wo_to_dict(w) for w in rows]

    # ── 내부 헬퍼 ────────────────────────────────────────────

    def _generate_wo_number(self) -> str:
        year = datetime.now().year
        _WO_COUNTER[str(year)] = _WO_COUNTER.get(str(year), 0) + 1
        return f"WO-{year}-{_WO_COUNTER[str(year)]:05d}"

    def _persist_wo(self, wo: dict) -> None:
        try:
            from app.database.models import WorkOrder, WorkOrderHistory
            db_wo = WorkOrder(
                id=wo["id"],
                wo_number=wo["wo_number"],
                room_no=wo.get("room_no"),
                location=wo.get("location"),
                category=wo["category"],
                description=wo["description"],
                photo_urls=wo.get("photo_urls"),
                severity=wo["severity"],
                status=wo["status"],
                ai_classification=wo.get("ai_classification"),
                reported_by=wo["reported_by"],
                sla_deadline=datetime.fromisoformat(wo["sla_deadline"]),
            )
            self.db.add(db_wo)
            self.db.flush()
            for h in wo.get("history", []):
                self.db.add(WorkOrderHistory(
                    wo_id=wo["id"],
                    status=h["status"],
                    changed_by=h.get("changed_by"),
                    note=h.get("note"),
                ))
            self.db.flush()
        except Exception as exc:
            logger.error("WO DB 저장 실패: %s", exc)

    def _wo_to_dict(self, wo) -> dict:
        return {
            "id": wo.id,
            "wo_number": wo.wo_number,
            "room_no": wo.room_no,
            "category": wo.category,
            "description": wo.description,
            "ai_category": (wo.ai_classification or {}).get("category"),
            "ai_severity": (wo.ai_classification or {}).get("severity"),
            "severity": wo.severity,
            "status": wo.status,
            "reported_by": wo.reported_by,
            "reported_at": wo.reported_at.isoformat() if wo.reported_at else None,
            "assigned_to": wo.assigned_to,
            "sla_deadline": wo.sla_deadline.isoformat() if wo.sla_deadline else None,
            "history": [
                {
                    "status": h.status,
                    "changed_by": h.changed_by,
                    "changed_at": h.changed_at.isoformat() if h.changed_at else None,
                    "note": h.note,
                }
                for h in (wo.history or [])
            ],
            "photo_urls": wo.photo_urls or [],
            "parts_used": wo.parts_used or [],
            "resolution_note": wo.resolution_note,
            "actual_duration_min": wo.actual_duration_min,
            "external_vendor": wo.external_vendor,
            "escalated": wo.escalated,
        }

    def _get_all_wo_dicts(self) -> list[dict]:
        if not self.db:
            return []
        from app.database.models import WorkOrder
        rows = self.db.query(WorkOrder).all()
        return [self._wo_to_dict(w) for w in rows]
