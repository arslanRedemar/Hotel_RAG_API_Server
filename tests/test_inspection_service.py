"""Compliance & Audit — InspectionService 단위 테스트 (CA-F01~F13)"""

from datetime import date, datetime

import pytest

from app.inspections.service import InspectionService, calculate_schedule_dates

# ── 공용 픽스처 ────────────────────────────────────────────────


@pytest.fixture
def svc(db):
    return InspectionService(db=db)


@pytest.fixture
def kitchen_template():
    return {
        "name": "주방 위생 점검표",
        "type": "위생",
        "department_id": None,
        "frequency": "daily",
        "frequency_day": None,
        "legal_reference": "식품위생법 제3조",
        "items": [
            {
                "id": "h-001",
                "category": "온도 관리",
                "description": "냉장고 온도 4°C 이하 유지",
                "required": True,
                "photo_required_on_ng": True,
            },
            {
                "id": "h-002",
                "category": "식재료 관리",
                "description": "유통기한 확인",
                "required": True,
                "photo_required_on_ng": True,
            },
            {
                "id": "h-003",
                "category": "개인위생",
                "description": "위생모 착용",
                "required": True,
                "photo_required_on_ng": False,
            },
        ],
    }


@pytest.fixture
def fire_template():
    return {
        "name": "소방 시설 점검표",
        "type": "소방",
        "department_id": None,
        "frequency": "monthly",
        "frequency_day": 1,
        "legal_reference": "소방시설법 제12조",
        "items": [
            {
                "id": "f-001",
                "category": "소화기",
                "description": "소화기 위치 및 압력 확인",
                "required": True,
                "photo_required_on_ng": False,
            },
        ],
    }


# ── 스케줄 날짜 계산 단위 테스트 ─────────────────────────────────


class TestCalculateScheduleDates:
    def test_daily_generates_every_day(self):
        template = {"frequency": "daily", "frequency_day": None}
        from_date = date(2026, 3, 1)
        dates = calculate_schedule_dates(template, from_date, days_ahead=5)
        assert len(dates) == 5
        assert dates[0] == date(2026, 3, 1)
        assert dates[4] == date(2026, 3, 5)

    def test_weekly_generates_correct_weekday(self):
        # frequency_day=0 → 월요일
        template = {"frequency": "weekly", "frequency_day": 0}
        from_date = date(2026, 3, 1)  # 일요일
        dates = calculate_schedule_dates(template, from_date, days_ahead=14)
        for d in dates:
            assert d.weekday() == 0, f"{d} 는 월요일이 아님"

    def test_weekly_no_match_returns_empty(self):
        template = {"frequency": "weekly", "frequency_day": 6}  # 일요일
        from_date = date(2026, 3, 2)  # 월요일
        dates = calculate_schedule_dates(template, from_date, days_ahead=6)
        # 2026-03-02(월)~03-07(토) → 일요일 없음
        assert len(dates) == 0

    def test_monthly_generates_on_correct_day(self):
        template = {"frequency": "monthly", "frequency_day": 15}
        from_date = date(2026, 3, 1)
        dates = calculate_schedule_dates(template, from_date, days_ahead=60)
        assert all(d.day == 15 for d in dates)
        assert len(dates) == 2  # 3/15, 4/15

    def test_quarterly_generates_every_3_months(self):
        template = {"frequency": "quarterly", "frequency_day": 1}
        from_date = date(2026, 1, 1)
        dates = calculate_schedule_dates(template, from_date, days_ahead=365)
        months_with_dates = {d.month for d in dates}
        assert months_with_dates.issubset({3, 6, 9, 12})

    def test_annually_generates_once(self):
        # 1년(365일) 범위에서 연간 점검은 정확히 1회 (2026-01-01만 포함)
        template = {"frequency": "annually", "frequency_day": None}
        from_date = date(2026, 1, 1)
        dates = calculate_schedule_dates(template, from_date, days_ahead=365)
        assert len(dates) == 1
        assert dates[0] == date(2026, 1, 1)

    def test_12_months_daily_count(self):
        template = {"frequency": "daily", "frequency_day": None}
        from_date = date(2026, 1, 1)
        dates = calculate_schedule_dates(template, from_date, days_ahead=365)
        assert len(dates) == 365

    def test_unknown_frequency_returns_empty(self):
        template = {"frequency": "adhoc", "frequency_day": None}
        dates = calculate_schedule_dates(template, date(2026, 1, 1), days_ahead=30)
        assert len(dates) == 0


# ── 템플릿 CRUD ──────────────────────────────────────────────


class TestTemplateService:
    def test_create_template_persists(self, svc, kitchen_template, staff_user):
        tpl = svc.create_template(kitchen_template, created_by=staff_user.id)
        assert tpl["id"] is not None
        assert tpl["name"] == "주방 위생 점검표"
        assert tpl["type"] == "위생"
        assert len(tpl["items"]) == 3

    def test_get_template_by_id(self, svc, kitchen_template, staff_user):
        created = svc.create_template(kitchen_template, created_by=staff_user.id)
        fetched = svc.get_template(created["id"])
        assert fetched["name"] == "주방 위생 점검표"

    def test_get_nonexistent_template_returns_none(self, svc):
        result = svc.get_template("nonexistent-id")
        assert result is None

    def test_list_templates_filter_by_type(self, svc, kitchen_template, fire_template, staff_user):
        svc.create_template(kitchen_template, created_by=staff_user.id)
        svc.create_template(fire_template, created_by=staff_user.id)

        hygiene = svc.list_templates(type="위생")
        fire = svc.list_templates(type="소방")

        assert all(t["type"] == "위생" for t in hygiene)
        assert all(t["type"] == "소방" for t in fire)

    def test_list_templates_only_active(self, svc, kitchen_template, staff_user):
        tpl = svc.create_template(kitchen_template, created_by=staff_user.id)
        svc.deactivate_template(tpl["id"])

        active = svc.list_templates(is_active=True)
        assert all(t["is_active"] for t in active)

    def test_generate_schedules_creates_entries(self, svc, fire_template, staff_user):
        tpl = svc.create_template(fire_template, created_by=staff_user.id)
        # 월간 → 3개월
        schedules = svc.generate_schedules(tpl["id"], months=3)
        assert len(schedules) >= 1
        assert all(s["template_id"] == tpl["id"] for s in schedules)

    def test_generate_schedules_no_duplicates(self, svc, fire_template, staff_user):
        tpl = svc.create_template(fire_template, created_by=staff_user.id)
        svc.generate_schedules(tpl["id"], months=3)
        schedules_first = svc.get_schedules(template_id=tpl["id"])

        # 다시 생성해도 중복 없음
        svc.generate_schedules(tpl["id"], months=3)
        schedules_second = svc.get_schedules(template_id=tpl["id"])
        assert len(schedules_first) == len(schedules_second)


# ── 점검 기록 제출 ────────────────────────────────────────────


class TestRecordSubmission:
    def _make_items(self, results: dict[str, str], notes: dict = None, photos: dict = None):
        notes = notes or {}
        photos = photos or {}
        return [
            {
                "item_id": "h-001",
                "result": results.get("h-001", "OK"),
                "note": notes.get("h-001"),
                "photo_url": photos.get("h-001"),
            },
            {
                "item_id": "h-002",
                "result": results.get("h-002", "OK"),
                "note": notes.get("h-002"),
                "photo_url": photos.get("h-002"),
            },
            {
                "item_id": "h-003",
                "result": results.get("h-003", "OK"),
                "note": notes.get("h-003"),
                "photo_url": photos.get("h-003"),
            },
        ]

    def test_all_ok_overall_result_pass(self, svc, kitchen_template, staff_user):
        tpl = svc.create_template(kitchen_template, created_by=staff_user.id)
        items = self._make_items({"h-001": "OK", "h-002": "OK", "h-003": "OK"})
        record = svc.submit_record(
            template_id=tpl["id"],
            location="주방 A구역",
            inspector_id=staff_user.id,
            inspector_name=staff_user.name,
            items=items,
            inspected_at=datetime.utcnow(),
        )
        assert record["overall_result"] == "pass"
        assert record["ng_count"] == 0

    def test_one_ng_overall_conditional_pass(self, svc, kitchen_template, staff_user):
        tpl = svc.create_template(kitchen_template, created_by=staff_user.id)
        items = self._make_items(
            {"h-001": "NG", "h-002": "OK", "h-003": "OK"},
            notes={"h-001": "온도 5°C 초과"},
            photos={"h-001": "http://img/1.jpg"},
        )
        record = svc.submit_record(
            template_id=tpl["id"],
            location="주방 A구역",
            inspector_id=staff_user.id,
            inspector_name=staff_user.name,
            items=items,
            inspected_at=datetime.utcnow(),
        )
        assert record["overall_result"] == "conditional_pass"
        assert record["ng_count"] == 1

    def test_three_ng_overall_fail(self, svc, kitchen_template, staff_user):
        tpl = svc.create_template(kitchen_template, created_by=staff_user.id)
        items = self._make_items(
            {"h-001": "NG", "h-002": "NG", "h-003": "NG"},
            notes={"h-001": "불량1", "h-002": "불량2", "h-003": "불량3"},
            photos={"h-001": "http://img/1.jpg", "h-002": "http://img/2.jpg"},
        )
        record = svc.submit_record(
            template_id=tpl["id"],
            location="주방 B구역",
            inspector_id=staff_user.id,
            inspector_name=staff_user.name,
            items=items,
            inspected_at=datetime.utcnow(),
        )
        assert record["overall_result"] == "fail"

    def test_ng_without_note_raises_error(self, svc, kitchen_template, staff_user):
        tpl = svc.create_template(kitchen_template, created_by=staff_user.id)
        items = self._make_items({"h-001": "NG"})  # note 없음
        with pytest.raises(ValueError, match="비고"):
            svc.submit_record(
                template_id=tpl["id"],
                location="주방",
                inspector_id=staff_user.id,
                inspector_name=staff_user.name,
                items=items,
                inspected_at=datetime.utcnow(),
            )

    def test_ng_photo_required_without_photo_raises_error(self, svc, kitchen_template, staff_user):
        tpl = svc.create_template(kitchen_template, created_by=staff_user.id)
        items = self._make_items(
            {"h-001": "NG"},
            notes={"h-001": "온도 초과"},
            # h-001은 photo_required_on_ng=True인데 photo_url 없음
        )
        with pytest.raises(ValueError, match="사진"):
            svc.submit_record(
                template_id=tpl["id"],
                location="주방",
                inspector_id=staff_user.id,
                inspector_name=staff_user.name,
                items=items,
                inspected_at=datetime.utcnow(),
            )

    def test_signature_auto_generated(self, svc, kitchen_template, staff_user):
        tpl = svc.create_template(kitchen_template, created_by=staff_user.id)
        items = self._make_items({})
        record = svc.submit_record(
            template_id=tpl["id"],
            location="주방",
            inspector_id=staff_user.id,
            inspector_name=staff_user.name,
            items=items,
            inspected_at=datetime.utcnow(),
        )
        assert staff_user.name in record["signature"]
        assert "|" in record["signature"]

    def test_na_items_not_counted_in_ng(self, svc, kitchen_template, staff_user):
        tpl = svc.create_template(kitchen_template, created_by=staff_user.id)
        items = self._make_items({"h-001": "NA", "h-002": "OK", "h-003": "OK"})
        record = svc.submit_record(
            template_id=tpl["id"],
            location="주방",
            inspector_id=staff_user.id,
            inspector_name=staff_user.name,
            items=items,
            inspected_at=datetime.utcnow(),
        )
        assert record["ng_count"] == 0


# ── 조치 이력 ─────────────────────────────────────────────────


class TestCorrectiveActions:
    def test_add_corrective_action(self, svc, kitchen_template, staff_user):
        tpl = svc.create_template(kitchen_template, created_by=staff_user.id)
        items = [
            {"item_id": "h-001", "result": "NG", "note": "온도 초과", "photo_url": "http://img/1.jpg"},
            {"item_id": "h-002", "result": "OK", "note": None, "photo_url": None},
            {"item_id": "h-003", "result": "OK", "note": None, "photo_url": None},
        ]
        record = svc.submit_record(
            template_id=tpl["id"],
            location="주방",
            inspector_id=staff_user.id,
            inspector_name=staff_user.name,
            items=items,
            inspected_at=datetime.utcnow(),
        )
        action = svc.add_corrective_action(
            record_id=record["id"],
            item_id="h-001",
            action="냉장고 온도 재설정 완료",
            completed_by=staff_user.id,
        )
        assert action["item_id"] == "h-001"
        assert action["action"] == "냉장고 온도 재설정 완료"

    def test_get_corrective_actions(self, svc, kitchen_template, staff_user):
        tpl = svc.create_template(kitchen_template, created_by=staff_user.id)
        items = [
            {"item_id": "h-001", "result": "NG", "note": "불량", "photo_url": "http://img/1.jpg"},
            {"item_id": "h-002", "result": "OK", "note": None, "photo_url": None},
            {"item_id": "h-003", "result": "OK", "note": None, "photo_url": None},
        ]
        record = svc.submit_record(
            template_id=tpl["id"],
            location="주방",
            inspector_id=staff_user.id,
            inspector_name=staff_user.name,
            items=items,
            inspected_at=datetime.utcnow(),
        )
        svc.add_corrective_action(record["id"], "h-001", "조치 완료", staff_user.id)
        actions = svc.get_corrective_actions(record["id"])
        assert len(actions) == 1


# ── 통계 ──────────────────────────────────────────────────────


class TestReportStats:
    def test_get_stats_returns_expected_keys(self, svc, kitchen_template, staff_user):
        tpl = svc.create_template(kitchen_template, created_by=staff_user.id)
        items = [
            {"item_id": "h-001", "result": "OK", "note": None, "photo_url": None},
            {"item_id": "h-002", "result": "NG", "note": "불량", "photo_url": "http://img/1.jpg"},
            {"item_id": "h-003", "result": "OK", "note": None, "photo_url": None},
        ]
        svc.submit_record(
            template_id=tpl["id"],
            location="주방",
            inspector_id=staff_user.id,
            inspector_name=staff_user.name,
            items=items,
            inspected_at=datetime.utcnow(),
        )
        stats = svc.get_stats()
        assert "total_inspections" in stats
        assert "pass_count" in stats
        assert "ng_rate_pct" in stats
        assert stats["total_inspections"] >= 1
