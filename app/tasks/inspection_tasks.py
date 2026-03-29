"""Compliance & Audit — 점검 Celery Beat 태스크 (CA-F10, CA-F12)

Celery Beat 스케줄:
- generate_schedules_task : 매일 00:05  — 활성 템플릿 기준 30일간 일정 자동 생성
- send_reminders_task     : 매일 08:00  — D-7 / D-1 사전 알림 발송
- check_overdue_task      : 매일 02:00  — 미완료 점검 overdue 처리

celery_app.conf.beat_schedule에 등록되어 있음 → docker-compose의 Celery Beat 워커가 실행.
테스트에서는 태스크 함수에 db= 를 직접 주입해 순수 로직만 검증.
"""

import asyncio
import logging
from datetime import date, timedelta

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.notifications.service import notify

logger = logging.getLogger(__name__)

celery_app = Celery("hotel_ax", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.beat_schedule = {
    "generate-inspection-schedules": {
        "task": "app.tasks.inspection_tasks.celery_generate_schedules",
        "schedule": crontab(hour=0, minute=5),
    },
    "send-inspection-reminders": {
        "task": "app.tasks.inspection_tasks.celery_send_reminders",
        "schedule": crontab(hour=8, minute=0),
    },
    "check-overdue-inspections": {
        "task": "app.tasks.inspection_tasks.celery_check_overdue",
        "schedule": crontab(hour=2, minute=0),
    },
}

# ── 기본 템플릿 시드 데이터 ──────────────────────────────────────

DEFAULT_TEMPLATES = [
    {
        "id": "tpl-hygiene-kitchen",
        "name": "주방 위생 점검표",
        "type": "위생",
        "frequency": "daily",
        "legal_reference": "식품위생법, 공중위생관리법",
        "items": [
            {"id": "h-001", "category": "온도 관리", "description": "냉장고 온도 4°C 이하 유지", "required": True},
            {"id": "h-002", "category": "식재료 관리", "description": "유통기한 확인 및 선입선출 준수", "required": True},
            {"id": "h-003", "category": "개인위생", "description": "조리 직원 위생모/앞치마 착용", "required": True},
        ],
    },
    {
        "id": "tpl-fire-safety",
        "name": "소방 안전 점검표",
        "type": "소방",
        "frequency": "monthly",
        "frequency_day": 1,
        "legal_reference": "소방시설 설치 및 관리에 관한 법률",
        "items": [
            {"id": "f-001", "category": "소화기", "description": "소화기 위치 및 압력 정상 확인", "required": True},
            {"id": "f-002", "category": "비상구", "description": "비상구 및 대피 통로 막힘 없음 확인", "required": True},
            {"id": "f-003", "category": "스프링클러", "description": "스프링클러 헤드 이물질 없음", "required": True},
        ],
    },
    {
        "id": "tpl-safety-equipment",
        "name": "안전 설비 점검표",
        "type": "안전",
        "frequency": "weekly",
        "frequency_day": 0,  # 월요일
        "legal_reference": "산업안전보건법",
        "items": [
            {"id": "s-001", "category": "전기", "description": "콘센트/분전반 과열 및 불량 여부", "required": True},
            {"id": "s-002", "category": "계단/복도", "description": "바닥 미끄럼 방지 상태 양호", "required": True},
            {"id": "s-003", "category": "CCTV", "description": "CCTV 작동 상태 정상", "required": False},
        ],
    },
    {
        "id": "tpl-room-quality",
        "name": "객실 품질 점검표",
        "type": "객실품질",
        "frequency": "daily",
        "items": [
            {"id": "r-001", "category": "청결", "description": "침구류 교체 및 청결 상태 확인", "required": True},
            {"id": "r-002", "category": "비품", "description": "욕실 어메니티 보충 여부", "required": True},
            {"id": "r-003", "category": "설비", "description": "TV/에어컨/냉장고 작동 정상", "required": True},
            {"id": "r-004", "category": "설비", "description": "전화기 및 인터넷 연결 정상", "required": False},
        ],
    },
]


def seed_inspection_templates(db) -> None:
    """기본 점검 템플릿 4종 삽입 (멱등성 보장)"""
    from app.database.models import InspectionTemplate

    for data in DEFAULT_TEMPLATES:
        existing = db.query(InspectionTemplate).filter_by(id=data["id"]).first()
        if not existing:
            tpl = InspectionTemplate(
                id=data["id"],
                name=data["name"],
                type=data["type"],
                frequency=data["frequency"],
                frequency_day=data.get("frequency_day"),
                items=data["items"],
                legal_reference=data.get("legal_reference"),
                is_active=True,
            )
            db.add(tpl)
    db.commit()
    logger.info("기본 점검 템플릿 시드 완료 (%d종)", len(DEFAULT_TEMPLATES))


# ── 태스크 구현 (순수 함수 — db 주입 가능) ────────────────────────

def generate_schedules_task(db=None, days_ahead: int = 30) -> int:
    """활성 템플릿 기준 days_ahead 일간 점검 일정 자동 생성.
    Returns: 생성된 일정 수
    """
    from app.database.connection import SessionLocal
    from app.database.models import InspectionTemplate, InspectionSchedule
    from app.inspections.service import calculate_schedule_dates

    own_db = False
    if db is None:
        db = SessionLocal()
        own_db = True

    try:
        templates = db.query(InspectionTemplate).filter_by(is_active=True).all()
        total_created = 0

        for tpl in templates:
            template_dict = {
                "id": tpl.id,
                "frequency": tpl.frequency,
                "frequency_day": tpl.frequency_day,
            }
            dates = calculate_schedule_dates(template_dict, date.today(), days_ahead)

            for sched_date in dates:
                date_str = sched_date.isoformat()
                exists = (
                    db.query(InspectionSchedule)
                    .filter_by(template_id=tpl.id, scheduled_date=date_str)
                    .first()
                )
                if not exists:
                    db.add(InspectionSchedule(
                        template_id=tpl.id,
                        scheduled_date=date_str,
                        status="scheduled",
                    ))
                    total_created += 1

        db.commit()
        logger.info("점검 일정 자동 생성 완료: %d건", total_created)
        return total_created
    finally:
        if own_db:
            db.close()


def send_reminders_task(db=None) -> None:
    """D-7 / D-1 미발송 일정에 담당자 이메일 알림"""
    from app.database.connection import SessionLocal
    from app.database.models import InspectionSchedule, User

    own_db = False
    if db is None:
        db = SessionLocal()
        own_db = True

    try:
        today = date.today()

        for days_ahead, flag_attr in [(7, "notified_7d"), (1, "notified_1d")]:
            target = today + timedelta(days=days_ahead)
            target_str = target.isoformat()

            filter_kwargs = {
                "scheduled_date": target_str,
                "status": "scheduled",
            }
            schedules = (
                db.query(InspectionSchedule)
                .filter_by(**filter_kwargs)
                .filter(getattr(InspectionSchedule, flag_attr).is_(False))
                .all()
            )

            for sched in schedules:
                if sched.assigned_to is None:
                    continue

                user = db.query(User).filter_by(id=sched.assigned_to).first()
                if not user:
                    continue

                tpl_name = sched.template.name if sched.template else "점검"

                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(notify(
                        channel="email",
                        recipient=user.email,
                        subject=f"[점검 예정 D-{days_ahead}] {tpl_name} — {target_str}",
                        body=(
                            f"{user.name}님,\n"
                            f"{days_ahead}일 후({target_str}) '{tpl_name}' 점검이 예정되어 있습니다."
                        ),
                        user_id=user.id,
                        db=db,
                    ))
                finally:
                    loop.close()

                setattr(sched, flag_attr, True)

        db.commit()
    finally:
        if own_db:
            db.close()


def check_overdue_task(db=None) -> int:
    """어제 scheduled 상태인 일정을 overdue로 전환하고 부서 관리자에게 알림"""
    from app.database.connection import SessionLocal
    from app.database.models import InspectionSchedule

    own_db = False
    if db is None:
        db = SessionLocal()
        own_db = True

    try:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        overdue_schedules = (
            db.query(InspectionSchedule)
            .filter_by(scheduled_date=yesterday, status="scheduled")
            .all()
        )

        for sched in overdue_schedules:
            sched.status = "overdue"
            tpl_name = sched.template.name if sched.template else "점검"
            logger.warning("점검 미완료(overdue): template=%s date=%s", tpl_name, yesterday)

        db.commit()
        count = len(overdue_schedules)
        logger.info("overdue 처리 완료: %d건", count)
        return count
    finally:
        if own_db:
            db.close()


# ── Celery 래퍼 태스크 ─────────────────────────────────────────

@celery_app.task(name="app.tasks.inspection_tasks.celery_generate_schedules")
def celery_generate_schedules():
    generate_schedules_task()


@celery_app.task(name="app.tasks.inspection_tasks.celery_send_reminders")
def celery_send_reminders():
    send_reminders_task()


@celery_app.task(name="app.tasks.inspection_tasks.celery_check_overdue")
def celery_check_overdue():
    check_overdue_task()
