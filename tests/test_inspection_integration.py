"""Compliance & Audit DB 통합 테스트 (service.py 커버리지 보완)"""

from datetime import datetime, timedelta

import pytest

from app.inspections.service import InspectionService


@pytest.fixture
def svc(db):
    return InspectionService(db=db)


@pytest.fixture
def hygiene_template_data():
    return {
        "name": "통합테스트 위생 점검표",
        "type": "위생",
        "department_id": None,
        "frequency": "weekly",
        "frequency_day": 1,  # 화요일
        "legal_reference": "식품위생법",
        "items": [
            {
                "id": "t-001",
                "category": "온도",
                "description": "냉장고 온도",
                "required": True,
                "photo_required_on_ng": False,
            },
            {
                "id": "t-002",
                "category": "청결",
                "description": "조리대 청결",
                "required": True,
                "photo_required_on_ng": False,
            },
        ],
    }


class TestTemplatePersistence:
    def test_template_created_and_fetched_from_db(self, svc, staff_user, hygiene_template_data):
        from app.database.models import InspectionTemplate

        created = svc.create_template(hygiene_template_data, created_by=staff_user.id)
        db_tpl = svc.db.query(InspectionTemplate).filter_by(id=created["id"]).first()
        assert db_tpl is not None
        assert db_tpl.name == "통합테스트 위생 점검표"
        assert db_tpl.frequency == "weekly"

    def test_deactivate_template(self, svc, staff_user, hygiene_template_data):
        from app.database.models import InspectionTemplate

        created = svc.create_template(hygiene_template_data, created_by=staff_user.id)
        svc.deactivate_template(created["id"])

        db_tpl = svc.db.query(InspectionTemplate).filter_by(id=created["id"]).first()
        assert db_tpl.is_active is False


class TestSchedulePersistence:
    def test_generate_schedules_saved_to_db(self, svc, staff_user):
        from app.database.models import InspectionSchedule

        tpl_data = {
            "name": "월간 점검",
            "type": "소방",
            "department_id": None,
            "frequency": "monthly",
            "frequency_day": 1,
            "legal_reference": None,
            "items": [{"id": "f-001", "category": "소화기", "description": "압력 확인", "required": True, "photo_required_on_ng": False}],
        }
        tpl = svc.create_template(tpl_data, created_by=staff_user.id)
        schedules = svc.generate_schedules(tpl["id"], months=3)

        assert len(schedules) >= 1
        db_sched = svc.db.query(InspectionSchedule).filter_by(template_id=tpl["id"]).all()
        assert len(db_sched) == len(schedules)

    def test_no_duplicate_schedules(self, svc, staff_user):
        from app.database.models import InspectionSchedule

        tpl_data = {
            "name": "중복방지 테스트",
            "type": "안전",
            "department_id": None,
            "frequency": "monthly",
            "frequency_day": 15,
            "legal_reference": None,
            "items": [{"id": "s-001", "category": "안전", "description": "비상구 확인", "required": True, "photo_required_on_ng": False}],
        }
        tpl = svc.create_template(tpl_data, created_by=staff_user.id)
        svc.generate_schedules(tpl["id"], months=3)
        first_count = svc.db.query(InspectionSchedule).filter_by(template_id=tpl["id"]).count()

        svc.generate_schedules(tpl["id"], months=3)
        second_count = svc.db.query(InspectionSchedule).filter_by(template_id=tpl["id"]).count()

        assert first_count == second_count


class TestRecordPersistence:
    def test_record_persisted_immutably(self, svc, staff_user):
        from app.database.models import InspectionRecord

        tpl_data = {
            "name": "객실 품질 점검",
            "type": "객실품질",
            "department_id": None,
            "frequency": "adhoc",
            "frequency_day": None,
            "legal_reference": None,
            "items": [
                {"id": "r-001", "category": "청결", "description": "침구 청결", "required": True, "photo_required_on_ng": False},
            ],
        }
        tpl = svc.create_template(tpl_data, created_by=staff_user.id)
        items = [{"item_id": "r-001", "result": "OK", "note": None, "photo_url": None}]

        record = svc.submit_record(
            template_id=tpl["id"],
            location="501호",
            inspector_id=staff_user.id,
            inspector_name=staff_user.name,
            items=items,
            inspected_at=datetime.utcnow(),
        )
        db_rec = svc.db.query(InspectionRecord).filter_by(id=record["id"]).first()
        assert db_rec is not None
        assert db_rec.overall_result == "pass"
        assert db_rec.ng_count == 0

    def test_multiple_records_list_query(self, svc, staff_user):
        tpl_data = {
            "name": "다건 점검표",
            "type": "위생",
            "department_id": None,
            "frequency": "daily",
            "frequency_day": None,
            "legal_reference": None,
            "items": [
                {"id": "x-001", "category": "청결", "description": "청결 확인", "required": True, "photo_required_on_ng": False},
            ],
        }
        tpl = svc.create_template(tpl_data, created_by=staff_user.id)
        items = [{"item_id": "x-001", "result": "OK", "note": None, "photo_url": None}]

        svc.submit_record(tpl["id"], "주방1", staff_user.id, staff_user.name, items, datetime.utcnow())
        svc.submit_record(tpl["id"], "주방2", staff_user.id, staff_user.name, items, datetime.utcnow())

        all_records = svc.list_records()
        assert len(all_records) >= 2

    def test_list_records_filter_by_type(self, svc, staff_user):
        tpl_data = {
            "name": "소방 점검",
            "type": "소방",
            "department_id": None,
            "frequency": "monthly",
            "frequency_day": 1,
            "legal_reference": None,
            "items": [
                {"id": "ff-001", "category": "소화기", "description": "확인", "required": True, "photo_required_on_ng": False},
            ],
        }
        tpl = svc.create_template(tpl_data, created_by=staff_user.id)
        items = [{"item_id": "ff-001", "result": "OK", "note": None, "photo_url": None}]
        svc.submit_record(tpl["id"], "1층 로비", staff_user.id, staff_user.name, items, datetime.utcnow())

        fire_records = svc.list_records(type="소방")
        assert all(r.get("type") == "소방" for r in fire_records)


class TestCorrectiveActionPersistence:
    def test_corrective_action_saved(self, svc, staff_user):
        from app.database.models import InspectionCorrectiveAction

        tpl_data = {
            "name": "조치 테스트",
            "type": "안전",
            "department_id": None,
            "frequency": "monthly",
            "frequency_day": 1,
            "legal_reference": None,
            "items": [
                {"id": "ca-001", "category": "안전", "description": "안전망", "required": True, "photo_required_on_ng": False},
                {"id": "ca-002", "category": "안전", "description": "소화기", "required": True, "photo_required_on_ng": False},
            ],
        }
        tpl = svc.create_template(tpl_data, created_by=staff_user.id)
        items = [
            {"item_id": "ca-001", "result": "NG", "note": "파손 발견", "photo_url": None},
            {"item_id": "ca-002", "result": "OK", "note": None, "photo_url": None},
        ]
        record = svc.submit_record(
            tpl["id"], "2층", staff_user.id, staff_user.name, items, datetime.utcnow()
        )
        svc.add_corrective_action(record["id"], "ca-001", "안전망 교체 완료", staff_user.id)

        db_action = svc.db.query(InspectionCorrectiveAction).filter_by(
            record_id=record["id"]
        ).first()
        assert db_action is not None
        assert db_action.item_id == "ca-001"


class TestStatsIntegration:
    def test_stats_from_db(self, svc, staff_user):
        tpl_data = {
            "name": "통계 테스트 점검",
            "type": "위생",
            "department_id": None,
            "frequency": "daily",
            "frequency_day": None,
            "legal_reference": None,
            "items": [
                {"id": "st-001", "category": "온도", "description": "온도 확인", "required": True, "photo_required_on_ng": False},
            ],
        }
        tpl = svc.create_template(tpl_data, created_by=staff_user.id)
        items_ok = [{"item_id": "st-001", "result": "OK", "note": None, "photo_url": None}]
        items_ng = [{"item_id": "st-001", "result": "NG", "note": "이상", "photo_url": None}]

        svc.submit_record(tpl["id"], "주방A", staff_user.id, staff_user.name, items_ok, datetime.utcnow())
        svc.submit_record(tpl["id"], "주방B", staff_user.id, staff_user.name, items_ng, datetime.utcnow())

        stats = svc.get_stats()
        assert stats["total_inspections"] >= 2
        assert stats["total_ng_count"] >= 1
