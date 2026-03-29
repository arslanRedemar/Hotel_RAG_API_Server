"""Work Order Celery 태스크 (WO-F22 SLA 에스컬레이션)

Celery Beat 스케줄:
- celery_check_sla_all : 매 30분 전체 미완료 WO SLA 체크

테스트에서는 함수에 db=를 직접 주입해 순수 로직만 검증.
"""

import asyncio
import logging
from datetime import datetime, timezone

from celery import Celery

from app.core.config import settings
from app.notifications.service import notify

logger = logging.getLogger(__name__)

celery_app = Celery("hotel_ax", broker=settings.redis_url, backend=settings.redis_url)

# ── 기본 AssigneeCapability 시드 데이터 ──────────────────────────

_DEFAULT_CATEGORIES = ["전기", "에어컨", "배관", "가구", "청결", "기타"]


def seed_assignee_capabilities(db, user_id: int) -> None:
    """해당 사용자에게 전체 카테고리 역량 데이터를 삽입 (멱등성 보장)"""
    from app.database.models import AssigneeCapability

    for priority, category in enumerate(_DEFAULT_CATEGORIES, start=1):
        existing = (
            db.query(AssigneeCapability)
            .filter_by(user_id=user_id, category=category)
            .first()
        )
        if not existing:
            db.add(AssigneeCapability(
                user_id=user_id,
                category=category,
                priority=priority,
                is_available=True,
            ))
    db.commit()
    logger.info("AssigneeCapability 시드 완료 (user_id=%s)", user_id)


# ── SLA 에스컬레이션 ────────────────────────────────────────────

def schedule_escalation_check(wo_id: str, db=None) -> None:
    """WO-F22: 특정 WO의 SLA 초과 여부를 확인하고 필요 시 에스컬레이션.

    Args:
        wo_id: 점검할 Work Order ID
        db: SQLAlchemy 세션 (None이면 새 세션 생성)
    """
    from app.database.connection import SessionLocal
    from app.database.models import WorkOrder

    own_db = False
    if db is None:
        db = SessionLocal()
        own_db = True

    try:
        wo = db.query(WorkOrder).filter_by(id=wo_id).first()
        if not wo:
            logger.debug("WO not found: %s", wo_id)
            return

        if wo.status in ("completed", "cancelled"):
            return

        if not wo.sla_deadline:
            return

        # timezone-aware 비교
        now = datetime.now(timezone.utc)
        deadline = wo.sla_deadline
        if hasattr(deadline, "tzinfo") and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)

        if isinstance(deadline, str):
            deadline = datetime.fromisoformat(deadline)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)

        if now <= deadline:
            return

        # 에스컬레이션 처리
        wo.escalated = True
        wo.escalated_at = datetime.now(timezone.utc)
        db.commit()

        logger.warning(
            "WO 에스컬레이션: wo_id=%s wo_number=%s severity=%s",
            wo_id, wo.wo_number, wo.severity,
        )

        _notify_escalation(wo, db)
    finally:
        if own_db:
            db.close()


def _notify_escalation(wo, db) -> None:
    """관리자에게 에스컬레이션 알림 발송"""
    from app.database.models import User

    managers = (
        db.query(User)
        .filter(User.role.in_(["admin", "manager"]), User.is_active.is_(True))
        .all()
    )

    for manager in managers:
        try:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(notify(
                    channel="email",
                    recipient=manager.email,
                    subject=f"[SLA 초과] Work Order {wo.wo_number} 에스컬레이션",
                    body=(
                        f"Work Order {wo.wo_number}이 SLA 기한을 초과했습니다.\n\n"
                        f"긴급도: {wo.severity.upper()}\n"
                        f"위치: {wo.room_no or wo.location or '미지정'}\n"
                        f"내용: {wo.description[:100]}\n\n"
                        "즉시 확인이 필요합니다."
                    ),
                    user_id=manager.id,
                    db=db,
                ))
            finally:
                loop.close()
        except Exception as exc:
            logger.warning("에스컬레이션 알림 실패 manager=%s: %s", manager.email, exc)


def check_all_sla(db=None) -> int:
    """전체 미완료 WO를 순회하며 SLA 초과 체크 (Celery Beat용)"""
    from app.database.connection import SessionLocal
    from app.database.models import WorkOrder

    own_db = False
    if db is None:
        db = SessionLocal()
        own_db = True

    try:
        wos = (
            db.query(WorkOrder)
            .filter(
                WorkOrder.status.not_in(["completed", "cancelled"]),
                WorkOrder.escalated.is_(False),
                WorkOrder.sla_deadline.isnot(None),
            )
            .all()
        )

        count = 0
        for wo in wos:
            try:
                schedule_escalation_check(wo_id=wo.id, db=db)
                db.expire_all()
                refreshed = db.query(WorkOrder).filter_by(id=wo.id).first()
                if refreshed and refreshed.escalated:
                    count += 1
            except Exception as exc:
                logger.error("SLA 체크 실패 wo_id=%s: %s", wo.id, exc)

        return count
    finally:
        if own_db:
            db.close()


# ── Celery 래퍼 ────────────────────────────────────────────────

@celery_app.task(name="app.tasks.work_order_tasks.celery_check_sla_all")
def celery_check_sla_all():
    check_all_sla()
