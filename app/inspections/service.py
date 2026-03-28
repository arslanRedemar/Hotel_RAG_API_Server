"""Compliance & Audit — 점검 서비스 (CA-F01~F13, CA-F30~F32)"""

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── 날짜 계산 (순수 함수, 테스트 용이) ──────────────────────────


def calculate_schedule_dates(
    template: dict, from_date: date, days_ahead: int
) -> list[date]:
    """템플릿 주기에 따라 from_date 기준 days_ahead 일간 점검 날짜 목록 반환"""
    frequency = template.get("frequency", "adhoc")
    freq_day = template.get("frequency_day")
    dates: list[date] = []

    for offset in range(days_ahead):
        target = from_date + timedelta(days=offset)

        if frequency == "daily":
            dates.append(target)

        elif frequency == "weekly":
            day = freq_day if freq_day is not None else 0
            if target.weekday() == day:
                dates.append(target)

        elif frequency == "monthly":
            day = freq_day if freq_day is not None else 1
            if target.day == day:
                dates.append(target)

        elif frequency == "quarterly":
            day = freq_day if freq_day is not None else 1
            if target.month % 3 == 0 and target.day == day:
                dates.append(target)

        elif frequency == "annually":
            if target.month == 1 and target.day == 1:
                dates.append(target)

        # adhoc 및 기타 → 빈 목록

    return dates


# ── InspectionService ─────────────────────────────────────────


class InspectionService:
    def __init__(self, db: Session):
        self.db = db

    # ── 템플릿 CRUD ──────────────────────────────────────────

    def create_template(self, data: dict, created_by: int) -> dict:
        from app.database.models import InspectionTemplate

        tpl = InspectionTemplate(
            id=str(uuid.uuid4()),
            name=data["name"],
            type=data["type"],
            department_id=data.get("department_id"),
            frequency=data.get("frequency", "monthly"),
            frequency_day=data.get("frequency_day"),
            items=data.get("items", []),
            legal_reference=data.get("legal_reference"),
            is_active=True,
            created_by=created_by,
        )
        self.db.add(tpl)
        self.db.flush()
        return self._template_to_dict(tpl)

    def get_template(self, template_id: str) -> Optional[dict]:
        from app.database.models import InspectionTemplate

        tpl = self.db.query(InspectionTemplate).filter_by(id=template_id).first()
        return self._template_to_dict(tpl) if tpl else None

    def list_templates(self, type: Optional[str] = None, is_active: Optional[bool] = None) -> list[dict]:
        from app.database.models import InspectionTemplate

        q = self.db.query(InspectionTemplate)
        if type is not None:
            q = q.filter(InspectionTemplate.type == type)
        if is_active is not None:
            q = q.filter(InspectionTemplate.is_active == is_active)
        return [self._template_to_dict(t) for t in q.all()]

    def deactivate_template(self, template_id: str) -> None:
        from app.database.models import InspectionTemplate

        tpl = self.db.query(InspectionTemplate).filter_by(id=template_id).first()
        if tpl:
            tpl.is_active = False
            self.db.flush()

    # ── 스케줄 생성 ─────────────────────────────────────────

    def generate_schedules(self, template_id: str, months: int = 12) -> list[dict]:
        from app.database.models import InspectionSchedule, InspectionTemplate

        tpl = self.db.query(InspectionTemplate).filter_by(id=template_id).first()
        if not tpl:
            return []

        template_dict = self._template_to_dict(tpl)
        from_date = date.today()
        days_ahead = months * 31  # 넉넉하게 계산
        schedule_dates = calculate_schedule_dates(template_dict, from_date, days_ahead)

        created = []
        for sched_date in schedule_dates:
            date_str = sched_date.isoformat()
            existing = (
                self.db.query(InspectionSchedule)
                .filter_by(template_id=template_id, scheduled_date=date_str)
                .first()
            )
            if not existing:
                sched = InspectionSchedule(
                    template_id=template_id,
                    scheduled_date=date_str,
                    status="scheduled",
                )
                self.db.add(sched)
                self.db.flush()
                created.append(self._schedule_to_dict(sched))

        return created

    def get_schedules(
        self,
        template_id: Optional[str] = None,
        status: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[dict]:
        from app.database.models import InspectionSchedule

        q = self.db.query(InspectionSchedule)
        if template_id:
            q = q.filter(InspectionSchedule.template_id == template_id)
        if status:
            q = q.filter(InspectionSchedule.status == status)
        if from_date:
            q = q.filter(InspectionSchedule.scheduled_date >= from_date)
        if to_date:
            q = q.filter(InspectionSchedule.scheduled_date <= to_date)
        return [self._schedule_to_dict(s) for s in q.order_by(InspectionSchedule.scheduled_date).all()]

    def get_today_schedules(self) -> list[dict]:
        today_str = date.today().isoformat()
        return self.get_schedules(from_date=today_str, to_date=today_str)

    # ── 점검 기록 제출 (불변) ────────────────────────────────

    def submit_record(
        self,
        template_id: str,
        location: str,
        inspector_id: int,
        inspector_name: str,
        items: list[dict],
        inspected_at: datetime,
        schedule_id: Optional[int] = None,
        source: str = "mobile",
    ) -> dict:
        from app.database.models import InspectionRecord, InspectionSchedule, InspectionTemplate

        tpl = self.db.query(InspectionTemplate).filter_by(id=template_id).first()
        if not tpl:
            raise ValueError(f"템플릿 {template_id}을 찾을 수 없습니다")

        template_items: dict[str, dict] = {item["id"]: item for item in (tpl.items or [])}

        # NG 검증
        for item in items:
            if item.get("result") != "NG":
                continue
            item_def = template_items.get(item["item_id"], {})
            if not item.get("note"):
                desc = item_def.get("description", item["item_id"])
                raise ValueError(f"'{desc}' 항목에 NG 비고 입력이 필요합니다")
            if item_def.get("photo_required_on_ng") and not item.get("photo_url"):
                desc = item_def.get("description", item["item_id"])
                raise ValueError(f"'{desc}' 항목에 NG 사진 첨부가 필요합니다")

        ng_count = sum(1 for i in items if i.get("result") == "NG")
        overall = "fail" if ng_count >= 3 else ("conditional_pass" if ng_count > 0 else "pass")

        submitted_at = datetime.utcnow()
        signature = f"{inspector_name} | {submitted_at.isoformat()}"
        record_id = str(uuid.uuid4())

        record = InspectionRecord(
            id=record_id,
            schedule_id=schedule_id,
            template_id=template_id,
            location=location,
            inspector_id=inspector_id,
            inspector_name=inspector_name,
            inspected_at=inspected_at,
            submitted_at=submitted_at,
            overall_result=overall,
            items=items,
            ng_count=ng_count,
            signature=signature,
            source=source,
        )
        self.db.add(record)

        if schedule_id:
            sched = self.db.query(InspectionSchedule).filter_by(id=schedule_id).first()
            if sched:
                sched.status = "completed"

        self.db.flush()
        return self._record_to_dict(record)

    def get_record(self, record_id: str) -> Optional[dict]:
        from app.database.models import InspectionRecord

        rec = self.db.query(InspectionRecord).filter_by(id=record_id).first()
        return self._record_to_dict(rec) if rec else None

    def list_records(
        self,
        type: Optional[str] = None,
        inspector_id: Optional[int] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        from app.database.models import InspectionRecord, InspectionTemplate

        q = self.db.query(InspectionRecord)
        if type:
            q = q.join(InspectionTemplate).filter(InspectionTemplate.type == type)
        if inspector_id:
            q = q.filter(InspectionRecord.inspector_id == inspector_id)
        if from_date:
            q = q.filter(InspectionRecord.inspected_at >= from_date)
        if to_date:
            q = q.filter(InspectionRecord.inspected_at <= to_date)

        records = q.order_by(InspectionRecord.inspected_at.desc()).offset(offset).limit(limit).all()
        result = []
        for rec in records:
            d = self._record_to_dict(rec)
            if rec.template:
                d["type"] = rec.template.type
            result.append(d)
        return result

    # ── 조치 이력 ────────────────────────────────────────────

    def add_corrective_action(
        self,
        record_id: str,
        item_id: str,
        action: str,
        completed_by: int,
        work_order_id: Optional[str] = None,
        verification_photo_url: Optional[str] = None,
    ) -> dict:
        from app.database.models import InspectionCorrectiveAction

        ca = InspectionCorrectiveAction(
            record_id=record_id,
            item_id=item_id,
            action=action,
            work_order_id=work_order_id,
            completed_by=completed_by,
            completed_at=datetime.utcnow(),
            verification_photo_url=verification_photo_url,
        )
        self.db.add(ca)
        self.db.flush()
        return self._corrective_action_to_dict(ca)

    def get_corrective_actions(self, record_id: str) -> list[dict]:
        from app.database.models import InspectionCorrectiveAction

        actions = (
            self.db.query(InspectionCorrectiveAction)
            .filter_by(record_id=record_id)
            .all()
        )
        return [self._corrective_action_to_dict(a) for a in actions]

    # ── 통계 ─────────────────────────────────────────────────

    def get_stats(
        self,
        type: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> dict:
        records = self.list_records(type=type, from_date=from_date, to_date=to_date, limit=10000)

        total = len(records)
        pass_count = sum(1 for r in records if r["overall_result"] == "pass")
        cond_count = sum(1 for r in records if r["overall_result"] == "conditional_pass")
        fail_count = sum(1 for r in records if r["overall_result"] == "fail")
        total_items = sum(len(r.get("items", [])) for r in records)
        total_ng = sum(r.get("ng_count", 0) for r in records)

        return {
            "total_inspections": total,
            "pass_count": pass_count,
            "conditional_pass_count": cond_count,
            "fail_count": fail_count,
            "pass_rate_pct": round(pass_count / total * 100, 1) if total else 0.0,
            "total_items_checked": total_items,
            "total_ng_count": total_ng,
            "ng_rate_pct": round(total_ng / total_items * 100, 1) if total_items else 0.0,
        }

    # ── 직렬화 헬퍼 ─────────────────────────────────────────

    def _template_to_dict(self, tpl) -> dict:
        return {
            "id": tpl.id,
            "name": tpl.name,
            "type": tpl.type,
            "department_id": tpl.department_id,
            "frequency": tpl.frequency,
            "frequency_day": tpl.frequency_day,
            "items": tpl.items or [],
            "legal_reference": tpl.legal_reference,
            "is_active": tpl.is_active,
            "created_by": tpl.created_by,
            "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
        }

    def _schedule_to_dict(self, sched) -> dict:
        return {
            "id": sched.id,
            "template_id": sched.template_id,
            "scheduled_date": sched.scheduled_date,
            "assigned_to": sched.assigned_to,
            "status": sched.status,
            "notified_7d": sched.notified_7d,
            "notified_1d": sched.notified_1d,
        }

    def _record_to_dict(self, rec) -> dict:
        return {
            "id": rec.id,
            "schedule_id": rec.schedule_id,
            "template_id": rec.template_id,
            "location": rec.location,
            "inspector_id": rec.inspector_id,
            "inspector_name": rec.inspector_name,
            "inspected_at": rec.inspected_at.isoformat() if rec.inspected_at else None,
            "submitted_at": rec.submitted_at.isoformat() if rec.submitted_at else None,
            "overall_result": rec.overall_result,
            "items": rec.items or [],
            "ng_count": rec.ng_count,
            "signature": rec.signature,
            "source": rec.source,
        }

    def _corrective_action_to_dict(self, ca) -> dict:
        return {
            "id": ca.id,
            "record_id": ca.record_id,
            "item_id": ca.item_id,
            "action": ca.action,
            "work_order_id": ca.work_order_id,
            "completed_by": ca.completed_by,
            "completed_at": ca.completed_at.isoformat() if ca.completed_at else None,
            "verification_photo_url": ca.verification_photo_url,
            "created_at": ca.created_at.isoformat() if ca.created_at else None,
        }
