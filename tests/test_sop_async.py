"""SOP Celery 비동기 처리 TDD 테스트 (SOP-F01 async variant)

설계:
  POST /api/v1/sops/extract  → 즉시 {sop_id, status:"processing"} 반환 (블로킹 없음)
  GET  /api/v1/sops/{id}     → status:"processing" 또는 "draft" 확인 가능
  extract_sop_task(sop_id)   → OCR+AI 처리 후 SOP status를 "draft"로 업데이트
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.database.models import SOP


# ─────────────────────────────────────────────────────────────────────────────
# 픽스처
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def auth_headers(client, staff_user):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "staff@hotel.com", "password": "pass1234"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fake_pdf_bytes():
    """최소 유효 PDF 바이트"""
    return b"%PDF-1.4 fake content"


@pytest.fixture
def processing_sop(db, staff_user):
    """status='processing' SOP 픽스처"""
    sop = SOP(
        id=str(uuid.uuid4()),
        title="처리중 SOP",
        status="processing",
        version="1.0",
        created_by=staff_user.id,
        updated_by=staff_user.id,
        review_required=True,
    )
    db.add(sop)
    db.commit()
    db.refresh(sop)
    return sop


# ─────────────────────────────────────────────────────────────────────────────
# 1. API: POST /sops/extract → 즉시 반환 (비동기)
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractSOPAsync:
    def test_extract_returns_processing_status_immediately(
        self, client, auth_headers, fake_pdf_bytes
    ):
        """파일 업로드 시 즉시 status='processing'으로 반환 (LLM 호출 없음)"""
        mock_task = MagicMock()
        mock_task.id = "celery-task-id-123"

        with (
            patch("app.storage.service.file_storage.save") as mock_save,
            patch("app.tasks.sop_tasks.extract_sop_task.delay") as mock_delay,
        ):
            mock_save.return_value = {
                "file_type": "pdf",
                "storage_key": "sops/test_file.pdf",
            }
            mock_delay.return_value = mock_task

            resp = client.post(
                "/api/v1/sops/extract",
                files={"file": ("test.pdf", fake_pdf_bytes, "application/pdf")},
                headers=auth_headers,
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "processing"
        assert "sop_id" in data
        # Celery 태스크가 enqueue되었는지 확인
        mock_delay.assert_called_once()

    def test_extract_does_not_call_sop_service_directly(
        self, client, auth_headers, fake_pdf_bytes
    ):
        """비동기 모드에서 process_upload()를 직접 호출하지 않음 (Celery에 위임)"""
        with (
            patch("app.storage.service.file_storage.save") as mock_save,
            patch("app.tasks.sop_tasks.extract_sop_task.delay") as mock_delay,
            patch("app.sop.service.SOPService.process_upload") as mock_process,
        ):
            mock_save.return_value = {
                "file_type": "pdf",
                "storage_key": "sops/test_file.pdf",
            }
            mock_delay.return_value = MagicMock()

            client.post(
                "/api/v1/sops/extract",
                files={"file": ("test.pdf", fake_pdf_bytes, "application/pdf")},
                headers=auth_headers,
            )

        # SOPService.process_upload()가 라우터에서 직접 호출되지 않아야 함
        mock_process.assert_not_called()

    def test_extract_task_called_with_correct_args(
        self, client, auth_headers, fake_pdf_bytes, db
    ):
        """Celery 태스크에 올바른 인자(sop_id, file_path, file_type, department_id, uploaded_by) 전달"""
        captured = {}

        def capture_delay(sop_id, file_path, file_type, department_id, uploaded_by):
            captured["sop_id"] = sop_id
            captured["file_path"] = file_path
            captured["file_type"] = file_type
            captured["uploaded_by"] = uploaded_by
            return MagicMock()

        with (
            patch("app.storage.service.file_storage.save") as mock_save,
            patch("app.tasks.sop_tasks.extract_sop_task.delay", side_effect=capture_delay),
        ):
            mock_save.return_value = {
                "file_type": "pdf",
                "storage_key": "sops/test_file.pdf",
            }
            resp = client.post(
                "/api/v1/sops/extract",
                files={"file": ("test.pdf", fake_pdf_bytes, "application/pdf")},
                headers=auth_headers,
            )

        assert resp.status_code == 201
        sop_id = resp.json()["sop_id"]
        assert captured["sop_id"] == sop_id
        assert captured["file_type"] == "pdf"
        assert captured["uploaded_by"] is not None

    def test_extract_sop_persisted_as_processing_in_db(
        self, client, auth_headers, fake_pdf_bytes, db
    ):
        """비동기 처리 중 SOP가 DB에 status='processing'으로 저장됨"""
        with (
            patch("app.storage.service.file_storage.save") as mock_save,
            patch("app.tasks.sop_tasks.extract_sop_task.delay"),
        ):
            mock_save.return_value = {
                "file_type": "pdf",
                "storage_key": "sops/test_file.pdf",
            }
            resp = client.post(
                "/api/v1/sops/extract",
                files={"file": ("test.pdf", fake_pdf_bytes, "application/pdf")},
                headers=auth_headers,
            )

        assert resp.status_code == 201
        sop_id = resp.json()["sop_id"]

        sop = db.query(SOP).filter_by(id=sop_id).first()
        assert sop is not None
        assert sop.status == "processing"


# ─────────────────────────────────────────────────────────────────────────────
# 2. API: GET /sops/{id} — processing 상태 조회
# ─────────────────────────────────────────────────────────────────────────────


class TestGetSOPStatus:
    def test_get_processing_sop_returns_status(
        self, client, auth_headers, processing_sop
    ):
        """처리 중인 SOP 조회 시 status='processing' 반환"""
        resp = client.get(
            f"/api/v1/sops/{processing_sop.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

    def test_list_sops_includes_processing(self, client, auth_headers, processing_sop):
        """목록 조회에 processing 상태 SOP 포함"""
        resp = client.get("/api/v1/sops", headers=auth_headers)
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()]
        assert processing_sop.id in ids


# ─────────────────────────────────────────────────────────────────────────────
# 3. Celery 태스크: extract_sop_task
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractSOPTask:
    def test_task_updates_sop_to_draft_on_success(self, db, staff_user):
        """성공 시 SOP status를 'draft'로 업데이트하고 title/steps 채움"""
        sop = SOP(
            id=str(uuid.uuid4()),
            title="처리중",
            status="processing",
            version="1.0",
            source_file="/tmp/test.pdf",
            created_by=staff_user.id,
            updated_by=staff_user.id,
            review_required=True,
        )
        db.add(sop)
        db.commit()

        mock_extraction = {
            "title": "객실 청소 SOP",
            "steps": [{"step_no": 1, "action": "청소 시작"}],
            "checklist_items": [{"text": "청소 완료", "required": True}],
            "cautions": ["주의"],
            "review_required": False,
            "extraction_confidence": 0.92,
        }

        with (
            patch("app.sop.ocr.OCRProcessor.extract_text_from_pdf") as mock_ocr,
            patch("app.sop.extractor.SOPExtractor.extract") as mock_extract,
        ):
            mock_ocr.return_value = [{"page": 1, "text": "청소 절차", "confidence": 0.95, "engine_used": "pdfplumber"}]
            mock_extract.return_value = mock_extraction

            from app.tasks.sop_tasks import extract_sop_task
            extract_sop_task(sop.id, "/tmp/test.pdf", "pdf", None, staff_user.id, _db=db)

        db.expire_all()
        updated = db.query(SOP).filter_by(id=sop.id).first()
        assert updated.status == "draft"
        assert updated.title == "객실 청소 SOP"
        assert updated.extraction_confidence == 0.92

    def test_task_sets_failed_status_on_error(self, db, staff_user):
        """처리 실패 시 SOP status를 'failed'로 업데이트"""
        sop = SOP(
            id=str(uuid.uuid4()),
            title="처리중",
            status="processing",
            version="1.0",
            source_file="/tmp/bad.pdf",
            created_by=staff_user.id,
            updated_by=staff_user.id,
            review_required=True,
        )
        db.add(sop)
        db.commit()

        with patch("app.sop.ocr.OCRProcessor.extract_text_from_pdf", side_effect=RuntimeError("OCR 실패")):
            from app.tasks.sop_tasks import extract_sop_task
            # 예외가 외부로 전파되지 않고 status만 'failed'로 변경
            with pytest.raises(RuntimeError):
                extract_sop_task(sop.id, "/tmp/bad.pdf", "pdf", None, staff_user.id, _db=db)

        db.expire_all()
        updated = db.query(SOP).filter_by(id=sop.id).first()
        assert updated.status == "failed"

    def test_task_noop_when_sop_not_found(self, db, staff_user):
        """존재하지 않는 sop_id는 조용히 무시"""
        from app.tasks.sop_tasks import extract_sop_task
        # 예외 없이 종료되어야 함
        extract_sop_task("non-existent-id", "/tmp/x.pdf", "pdf", None, staff_user.id, _db=db)

    def test_task_skips_if_not_processing(self, db, staff_user):
        """status가 'processing'이 아닌 SOP는 재처리하지 않음 (멱등성)"""
        sop = SOP(
            id=str(uuid.uuid4()),
            title="완료 SOP",
            status="draft",
            version="1.0",
            source_file="/tmp/done.pdf",
            created_by=staff_user.id,
            updated_by=staff_user.id,
            review_required=True,
        )
        db.add(sop)
        db.commit()

        with patch("app.sop.ocr.OCRProcessor.extract_text_from_pdf") as mock_ocr:
            from app.tasks.sop_tasks import extract_sop_task
            extract_sop_task(sop.id, "/tmp/done.pdf", "pdf", None, staff_user.id, _db=db)
            mock_ocr.assert_not_called()
