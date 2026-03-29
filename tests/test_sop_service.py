"""SOP Service 통합 테스트 (인메모리 SQLite)"""

from unittest.mock import MagicMock, patch


from app.database.models import SOP, SOPVersionHistory
from app.sop.service import SOPService


def _make_mock_ocr(text="SOP 텍스트 내용", confidence=0.90):
    mock = MagicMock()
    mock.extract_text_from_pdf.return_value = [
        {"page": 1, "text": text, "confidence": confidence, "engine_used": "local"}
    ]
    return mock


def _make_mock_extractor(title="테스트 SOP", review=False, confidence=0.85):
    mock = MagicMock()
    mock.extract.return_value = {
        "title": title,
        "steps": [{"step_no": 1, "action": "고객에게 인사합니다", "responsible": None, "duration_min": None, "notes": None}],
        "checklist_items": [{"text": "신분증 확인", "required": True}],
        "cautions": ["주의사항"],
        "review_required": review,
        "extraction_confidence": confidence,
    }
    return mock


class TestSOPServiceProcessUpload:
    def test_creates_draft_sop(self, db, staff_user, test_dept):
        service = SOPService.__new__(SOPService)
        service.ocr = _make_mock_ocr()
        service.extractor = _make_mock_extractor()

        with patch("pathlib.Path.read_text", return_value="텍스트"):
            sop = service.process_upload(
                db=db,
                file_path="dummy.pdf",
                file_type="pdf",
                department_id=test_dept.id,
                uploaded_by=staff_user.id,
            )

        assert sop.status == "draft"
        assert sop.title == "테스트 SOP"
        assert sop.created_by == staff_user.id
        assert sop.department_id == test_dept.id

    def test_review_required_flag_propagated(self, db, staff_user, test_dept):
        service = SOPService.__new__(SOPService)
        service.ocr = _make_mock_ocr(confidence=0.50)
        service.extractor = _make_mock_extractor(review=True, confidence=0.50)

        with patch("pathlib.Path.read_text", return_value="텍스트"):
            sop = service.process_upload(
                db=db,
                file_path="dummy.pdf",
                file_type="pdf",
                department_id=test_dept.id,
                uploaded_by=staff_user.id,
            )

        assert sop.review_required is True

    def test_txt_file_reads_directly(self, db, staff_user, test_dept, tmp_path):
        txt_file = tmp_path / "sop.txt"
        txt_file.write_text("텍스트 파일 내용", encoding="utf-8")

        service = SOPService.__new__(SOPService)
        service.ocr = _make_mock_ocr()
        service.extractor = _make_mock_extractor()

        sop = service.process_upload(
            db=db,
            file_path=str(txt_file),
            file_type="txt",
            department_id=test_dept.id,
            uploaded_by=staff_user.id,
        )
        assert sop.id is not None

    def test_sop_persisted_in_db(self, db, staff_user, test_dept):
        service = SOPService.__new__(SOPService)
        service.ocr = _make_mock_ocr()
        service.extractor = _make_mock_extractor()

        with patch("pathlib.Path.read_text", return_value="텍스트"):
            sop = service.process_upload(
                db=db,
                file_path="dummy.pdf",
                file_type="pdf",
                department_id=test_dept.id,
                uploaded_by=staff_user.id,
            )

        fetched = db.get(SOP, sop.id)
        assert fetched is not None
        assert fetched.title == sop.title


class TestSOPServiceUpdate:
    def _make_draft_sop(self, db, user, dept, sop_id=None):
        import uuid
        sop = SOP(
            id=sop_id or str(uuid.uuid4()),
            title="원래 제목",
            department_id=dept.id,
            status="draft",
            version="1.0",
            steps=[],
            checklist_items=[],
            cautions=[],
            review_required=True,
            created_by=user.id,
            updated_by=user.id,
        )
        db.add(sop)
        db.commit()
        db.refresh(sop)
        return sop

    def test_updates_title(self, db, staff_user, test_dept):
        service = SOPService()
        sop = self._make_draft_sop(db, staff_user, test_dept)

        updated = service.update(db, sop, {"title": "수정된 제목"}, updated_by=staff_user.id)
        assert updated.title == "수정된 제목"

    def test_status_changes_to_under_review(self, db, staff_user, test_dept):
        service = SOPService()
        sop = self._make_draft_sop(db, staff_user, test_dept)

        service.update(db, sop, {"title": "변경"}, updated_by=staff_user.id)
        assert sop.status == "under_review"

    def test_ignores_unknown_fields(self, db, staff_user, test_dept):
        service = SOPService()
        sop = self._make_draft_sop(db, staff_user, test_dept)

        # 허용되지 않은 필드는 무시
        service.update(db, sop, {"status": "active", "title": "변경"}, updated_by=staff_user.id)
        # status는 update 메서드에서 허용 필드에 없으므로 그대로 under_review
        assert sop.status == "under_review"


class TestSOPServicePublish:
    def _make_draft_sop(self, db, user, dept, sop_id="sop-publish-test"):
        import uuid
        sop = SOP(
            id=sop_id or str(uuid.uuid4()),
            title="게시할 SOP",
            department_id=dept.id,
            status="draft",
            version="1.0",
            steps=[{"step_no": 1, "action": "절차", "responsible": None, "duration_min": None, "notes": None}],
            checklist_items=[],
            cautions=[],
            review_required=True,
            created_by=user.id,
            updated_by=user.id,
        )
        db.add(sop)
        db.commit()
        db.refresh(sop)
        return sop

    def test_status_becomes_active(self, db, manager_user, test_dept):
        service = SOPService()
        sop = self._make_draft_sop(db, manager_user, test_dept, "pub-test-1")

        with patch("app.tasks.sop_tasks.ingest_sop_task") as mock_task:
            mock_task.delay = MagicMock()
            result = service.publish(db, sop, publisher_id=manager_user.id)

        assert result.status == "active"
        assert result.review_required is False
        assert result.published_by == manager_user.id
        assert result.published_at is not None

    def test_version_history_saved(self, db, manager_user, test_dept):
        service = SOPService()
        sop = self._make_draft_sop(db, manager_user, test_dept, "pub-test-2")

        with patch("app.tasks.sop_tasks.ingest_sop_task") as mock_task:
            mock_task.delay = MagicMock()
            service.publish(db, sop, publisher_id=manager_user.id)

        history = db.query(SOPVersionHistory).filter_by(sop_id=sop.id).first()
        assert history is not None
        assert history.version == "1.0"
        assert "title" in history.snapshot


class TestSOPServiceAcknowledge:
    def _make_active_sop(self, db, user, dept):
        import uuid
        sop = SOP(
            id=str(uuid.uuid4()),
            title="확인할 SOP",
            department_id=dept.id,
            status="active",
            version="1.0",
            steps=[],
            checklist_items=[],
            cautions=[],
            review_required=False,
            created_by=user.id,
            updated_by=user.id,
        )
        db.add(sop)
        db.commit()
        db.refresh(sop)
        return sop

    def test_acknowledge_creates_record(self, db, staff_user, test_dept):
        service = SOPService()
        sop = self._make_active_sop(db, staff_user, test_dept)

        ack = service.acknowledge(db, sop, user_id=staff_user.id)
        assert ack.sop_id == sop.id
        assert ack.user_id == staff_user.id

    def test_duplicate_acknowledge_returns_existing(self, db, staff_user, test_dept):
        service = SOPService()
        sop = self._make_active_sop(db, staff_user, test_dept)

        ack1 = service.acknowledge(db, sop, user_id=staff_user.id)
        ack2 = service.acknowledge(db, sop, user_id=staff_user.id)
        assert ack1.id == ack2.id

    def test_acknowledge_stats(self, db, staff_user, manager_user, test_dept):
        service = SOPService()
        sop = self._make_active_sop(db, staff_user, test_dept)

        service.acknowledge(db, sop, user_id=staff_user.id)
        stats = service.get_acknowledge_stats(db, sop)

        assert stats["total_staff"] >= 1
        assert stats["acknowledged"] >= 1
        assert 0.0 <= stats["completion_rate"] <= 1.0
