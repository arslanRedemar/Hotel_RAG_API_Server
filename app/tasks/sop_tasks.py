"""SOP 비동기 Celery 태스크"""

import logging
from pathlib import Path

from celery import Celery

from app.core.config import settings

celery_app = Celery("hotel_ax", broker=settings.redis_url, backend=settings.redis_url)

logger = logging.getLogger(__name__)


def _run_extract_sop(
    sop_id: str,
    file_path: str,
    file_type: str,
    department_id: int | None,
    uploaded_by: int,
    _db=None,
) -> None:
    """SOP 비동기 처리: OCR → AI 추출 → SOP status 업데이트 (processing → draft)

    Args:
        sop_id: 처리할 SOP의 ID (status='processing'이어야 함)
        file_path: 업로드된 파일 경로
        file_type: 파일 타입 (pdf/txt/docx)
        department_id: 부서 ID
        uploaded_by: 업로드한 사용자 ID
        _db: 테스트용 DB 세션 주입 (None이면 새 세션 생성)
    """
    from app.database.connection import SessionLocal
    from app.database.models import SOP
    from app.sop.extractor import SOPExtractor
    from app.sop.ocr import OCRProcessor

    own_db = False
    if _db is None:
        _db = SessionLocal()
        own_db = True

    try:
        sop = _db.query(SOP).filter_by(id=sop_id).first()
        if not sop:
            logger.warning("extract_sop_task: SOP not found sop_id=%s", sop_id)
            return

        # 멱등성 보장: processing 상태가 아니면 재처리 안 함
        if sop.status != "processing":
            logger.info("extract_sop_task: SOP already processed sop_id=%s status=%s", sop_id, sop.status)
            return

        ocr = OCRProcessor()
        extractor = SOPExtractor()
        file_type = file_type.lower()

        # OCR / 텍스트 추출
        if file_type == "pdf":
            pages = ocr.extract_text_from_pdf(file_path)
        elif file_type in ("docx", "doc"):
            pages = ocr.extract_text_from_docx(file_path)
        else:
            text = Path(file_path).read_text(encoding="utf-8")
            pages = [{"page": 1, "text": text, "confidence": 1.0, "engine_used": "plaintext"}]

        full_text = "\n\n".join(p["text"] for p in pages)
        avg_ocr_confidence = sum(p["confidence"] for p in pages) / len(pages)

        # AI 구조 추출
        extraction = extractor.extract(full_text)

        # SOP 업데이트
        sop.title = extraction.get("title") or Path(file_path).stem
        sop.department_id = department_id
        sop.steps = extraction.get("steps", [])
        sop.checklist_items = extraction.get("checklist_items", [])
        sop.cautions = extraction.get("cautions", [])
        sop.review_required = extraction.get("review_required", True)
        sop.extraction_confidence = extraction.get("extraction_confidence")
        sop.ocr_confidence = round(avg_ocr_confidence, 3)
        sop.source_file = file_path
        sop.updated_by = uploaded_by
        sop.status = "draft"

        _db.commit()
        logger.info("SOP 비동기 처리 완료 sop_id=%s title=%s", sop_id, sop.title)

    except Exception as exc:
        logger.error("SOP 비동기 처리 실패 sop_id=%s: %s", sop_id, exc)
        try:
            sop = _db.query(SOP).filter_by(id=sop_id).first()
            if sop:
                sop.status = "failed"
                _db.commit()
        except Exception:
            pass
        raise
    finally:
        if own_db:
            _db.close()


@celery_app.task(
    name="app.tasks.sop_tasks.celery_extract_sop",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def celery_extract_sop(self, sop_id: str, file_path: str, file_type: str, department_id, uploaded_by: int):
    """Celery 래퍼 태스크 — _run_extract_sop 호출"""
    try:
        _run_extract_sop(sop_id, file_path, file_type, department_id, uploaded_by)
    except Exception as exc:
        raise self.retry(exc=exc)


# ── 공개 API: 라우터에서 .delay() 호출용 ───────────────────────────────────

class _ExtractSOPTaskProxy:
    """extract_sop_task.delay()를 Celery 태스크처럼 사용할 수 있는 래퍼"""

    def delay(self, sop_id, file_path, file_type, department_id, uploaded_by):
        return celery_extract_sop.delay(sop_id, file_path, file_type, department_id, uploaded_by)

    def __call__(self, sop_id, file_path, file_type, department_id, uploaded_by, _db=None):
        return _run_extract_sop(sop_id, file_path, file_type, department_id, uploaded_by, _db=_db)


extract_sop_task = _ExtractSOPTaskProxy()


# ── 레거시 태스크 ──────────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_sop_upload_task(self, sop_id: str, file_path: str, metadata: dict):
    """비동기 SOP 처리: OCR → AI 추출 → DB 저장 (레거시 — extract_sop_task 사용 권장)"""
    try:
        from app.database.connection import SessionLocal
        from app.sop.service import SOPService

        with SessionLocal() as db:
            service = SOPService()
            service.process_upload(
                db=db,
                file_path=file_path,
                file_type=metadata["file_type"],
                department_id=metadata.get("department_id"),
                uploaded_by=metadata["uploaded_by"],
            )
        logger.info("SOP 처리 완료 sop_id=%s", sop_id)
    except Exception as exc:
        logger.error("SOP 처리 실패 sop_id=%s: %s", sop_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def ingest_sop_task(self, sop_id: str):
    """확정된 SOP를 RAG 벡터 DB에 인덱싱"""
    try:
        from app.database.connection import SessionLocal
        from app.database.models import SOP
        from app.rag.ingest import ingest_sop_to_vector_store

        with SessionLocal() as db:
            sop = db.get(SOP, sop_id)
            if not sop:
                logger.warning("SOP not found: %s", sop_id)
                return
            chunk_ids = ingest_sop_to_vector_store(sop)
            sop.chroma_chunk_ids = chunk_ids
            db.commit()
        logger.info("SOP RAG 인덱싱 완료 sop_id=%s chunks=%d", sop_id, len(chunk_ids))
    except Exception as exc:
        logger.error("SOP 인덱싱 실패 sop_id=%s: %s", sop_id, exc)
        raise self.retry(exc=exc)
