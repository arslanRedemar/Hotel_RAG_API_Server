"""SOP 비동기 Celery 태스크"""

import logging

from celery import Celery

from app.core.config import settings

celery_app = Celery("hotel_ax", broker=settings.redis_url, backend=settings.redis_url)

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_sop_upload_task(self, sop_id: str, file_path: str, metadata: dict):
    """비동기 SOP 처리: OCR → AI 추출 → DB 저장"""
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
