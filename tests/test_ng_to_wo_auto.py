"""CA-F06 × WO-F01: NG 항목 → Work Order 자동 연동 테스트"""

from datetime import datetime

import pytest

from app.database.models import Department, InspectionTemplate, User
from app.auth.password import hash_password


# ── 픽스처 ────────────────────────────────────────────────────

@pytest.fixture
def ng_dept(db):
    dept = db.query(Department).filter_by(code="NG_TEST").first()
    if not dept:
        dept = Department(name="NG테스트부서", code="NG_TEST")
        db.add(dept)
        db.commit()
        db.refresh(dept)
    return dept


@pytest.fixture
def ng_inspector(db, ng_dept):
    user = db.query(User).filter_by(email="inspector@hotel.local").first()
    if not user:
        user = User(
            email="inspector@hotel.local",
            password_hash=hash_password("Inspector1!"),
            name="점검원",
            role="staff",
            department_id=ng_dept.id,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@pytest.fixture
def ng_template(db, ng_inspector):
    """NG 항목용 점검 템플릿"""
    import uuid
    tpl = InspectionTemplate(
        id=str(uuid.uuid4()),
        name="NG 자동연동 테스트 템플릿",
        type="room",
        frequency="daily",
        department_id=None,
        items=[
            {"id": "E01", "category": "electrical", "description": "전기 콘센트 상태", "required": True},
            {"id": "P01", "category": "plumbing", "description": "배수구 상태", "required": True},
        ],
        is_active=True,
        created_by=ng_inspector.id,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@pytest.fixture
def submitted_record(db, ng_template, ng_inspector):
    """NG 항목이 포함된 점검 기록"""
    from app.inspections.service import InspectionService
    svc = InspectionService(db)
    record = svc.submit_record(
        template_id=ng_template.id,
        location="305호",
        inspector_id=ng_inspector.id,
        inspector_name=ng_inspector.name,
        items=[
            {"item_id": "E01", "result": "NG", "note": "콘센트 과부하 감지"},
            {"item_id": "P01", "result": "OK"},
        ],
        inspected_at=datetime.utcnow(),
    )
    db.commit()
    return record


# ── 단위 테스트: 서비스 레벨 ─────────────────────────────────

class TestNGtoWOService:
    def test_add_corrective_action_without_auto_wo(self, db, submitted_record, ng_inspector):
        """auto_create_wo=False 시 WO 미생성"""
        from app.inspections.service import InspectionService
        from app.database.models import WorkOrder

        svc = InspectionService(db)
        ca = svc.add_corrective_action(
            record_id=submitted_record["id"],
            item_id="E01",
            action="전기 기사 점검 완료",
            completed_by=ng_inspector.id,
            auto_create_wo=False,
        )
        assert ca["work_order_id"] is None
        wo_count = db.query(WorkOrder).count()
        assert wo_count == 0

    def test_add_corrective_action_with_auto_wo(self, db, submitted_record, ng_inspector):
        """auto_create_wo=True 시 WO 자동 생성"""
        from app.inspections.service import InspectionService
        from app.database.models import WorkOrder

        svc = InspectionService(db)
        ca = svc.add_corrective_action(
            record_id=submitted_record["id"],
            item_id="E01",
            action="전기 기사 점검 필요",
            completed_by=ng_inspector.id,
            auto_create_wo=True,
        )
        # WO ID가 연결돼야 함
        assert ca["work_order_id"] is not None
        wo = db.query(WorkOrder).filter_by(id=ca["work_order_id"]).first()
        assert wo is not None

    def test_auto_wo_description_contains_item_info(self, db, submitted_record, ng_inspector):
        """자동 생성 WO 설명에 점검 항목 정보 포함"""
        from app.inspections.service import InspectionService
        from app.database.models import WorkOrder

        svc = InspectionService(db)
        ca = svc.add_corrective_action(
            record_id=submitted_record["id"],
            item_id="E01",
            action="점검 필요",
            completed_by=ng_inspector.id,
            auto_create_wo=True,
        )
        wo = db.query(WorkOrder).filter_by(id=ca["work_order_id"]).first()
        assert "305호" in wo.description or "E01" in wo.description or "전기" in wo.description

    def test_auto_wo_location_from_record(self, db, submitted_record, ng_inspector):
        """자동 생성 WO의 location이 점검 기록의 위치와 일치"""
        from app.inspections.service import InspectionService
        from app.database.models import WorkOrder

        svc = InspectionService(db)
        ca = svc.add_corrective_action(
            record_id=submitted_record["id"],
            item_id="E01",
            action="점검 필요",
            completed_by=ng_inspector.id,
            auto_create_wo=True,
        )
        wo = db.query(WorkOrder).filter_by(id=ca["work_order_id"]).first()
        assert wo.location == "305호" or wo.room_no == "305호"

    def test_multiple_ng_items_create_separate_wos(self, db, ng_template, ng_inspector):
        """두 NG 항목에 대해 각각 WO 생성"""
        from app.inspections.service import InspectionService
        from app.database.models import WorkOrder

        svc = InspectionService(db)
        record = svc.submit_record(
            template_id=ng_template.id,
            location="407호",
            inspector_id=ng_inspector.id,
            inspector_name=ng_inspector.name,
            items=[
                {"item_id": "E01", "result": "NG", "note": "콘센트 문제"},
                {"item_id": "P01", "result": "NG", "note": "배수 막힘"},
            ],
            inspected_at=datetime.utcnow(),
        )
        db.commit()

        before_count = db.query(WorkOrder).count()
        svc.add_corrective_action(record["id"], "E01", "전기 점검", ng_inspector.id, auto_create_wo=True)
        svc.add_corrective_action(record["id"], "P01", "배관 점검", ng_inspector.id, auto_create_wo=True)
        db.commit()

        after_count = db.query(WorkOrder).count()
        assert after_count - before_count == 2


# ── 통합 테스트: API 레벨 ─────────────────────────────────────

class TestNGtoWOAPI:
    @pytest.fixture
    def auth_headers(self, client, db, ng_inspector):
        r = client.post("/api/v1/auth/login", json={
            "email": "inspector@hotel.local",
            "password": "Inspector1!",
        })
        token = r.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_corrective_action_api_creates_wo(self, client, db, submitted_record, auth_headers):
        """API 통해 auto_create_wo=true 시 WO 생성"""
        from app.database.models import WorkOrder

        before = db.query(WorkOrder).count()
        r = client.post(
            f"/api/v1/inspection-records/{submitted_record['id']}/corrective-actions",
            json={
                "item_id": "E01",
                "action": "전기 기사 긴급 점검",
                "auto_create_wo": True,
            },
            headers=auth_headers,
        )
        assert r.status_code == 201
        data = r.json()
        assert data.get("work_order_id") is not None

        db.expire_all()
        after = db.query(WorkOrder).count()
        assert after > before

    def test_corrective_action_api_without_auto_wo(self, client, submitted_record, auth_headers):
        """API에서 auto_create_wo 없으면 WO 미생성"""
        r = client.post(
            f"/api/v1/inspection-records/{submitted_record['id']}/corrective-actions",
            json={
                "item_id": "E01",
                "action": "직접 수리 완료",
            },
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json().get("work_order_id") is None
