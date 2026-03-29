"""SOP 비즈니스 로직 통합 서비스"""

import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.database.models import SOP, SOPAcknowledgement, SOPVersionHistory
from app.sop.extractor import SOPExtractor
from app.sop.ocr import OCRProcessor

logger = logging.getLogger(__name__)


class SOPService:
    def __init__(self) -> None:
        self.ocr = OCRProcessor()
        self.extractor = SOPExtractor()

    # ── 업로드 처리 ───────────────────────────────────────────

    def process_upload(
        self,
        db: Session,
        file_path: str,
        file_type: str,
        department_id: int | None,
        uploaded_by: int,
    ) -> SOP:
        """파일 업로드 → OCR → AI 추출 → draft SOP 저장"""
        start = time.perf_counter()
        file_type = file_type.lower()

        # 텍스트 추출
        if file_type == "pdf":
            pages = self.ocr.extract_text_from_pdf(file_path)
        elif file_type in ("docx", "doc"):
            pages = self.ocr.extract_text_from_docx(file_path)
        else:
            text = Path(file_path).read_text(encoding="utf-8")
            pages = [{"page": 1, "text": text, "confidence": 1.0, "engine_used": "plaintext"}]

        full_text = "\n\n".join(p["text"] for p in pages)
        avg_ocr_confidence = sum(p["confidence"] for p in pages) / len(pages)

        # AI 구조 추출
        extraction = self.extractor.extract(full_text)

        sop = SOP(
            id=str(uuid.uuid4()),
            title=extraction.get("title") or Path(file_path).stem,
            department_id=department_id,
            steps=extraction.get("steps", []),
            checklist_items=extraction.get("checklist_items", []),
            cautions=extraction.get("cautions", []),
            review_required=extraction.get("review_required", True),
            extraction_confidence=extraction.get("extraction_confidence"),
            ocr_confidence=round(avg_ocr_confidence, 3),
            source_file=file_path,
            status="draft",
            version="1.0",
            created_by=uploaded_by,
            updated_by=uploaded_by,
        )
        db.add(sop)
        db.commit()
        db.refresh(sop)

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "SOP 처리 완료 sop_id=%s review_required=%s elapsed_ms=%d",
            sop.id, sop.review_required, elapsed_ms,
        )
        return sop

    # ── 수정 ─────────────────────────────────────────────────

    def update(
        self,
        db: Session,
        sop: SOP,
        updates: dict,
        updated_by: int,
    ) -> SOP:
        """SOP 내용 수정 (에디터 저장)"""
        allowed = {"title", "steps", "checklist_items", "cautions", "tags", "review_required"}
        for key, value in updates.items():
            if key in allowed:
                setattr(sop, key, value)
        sop.updated_by = updated_by
        sop.status = "under_review" if sop.status == "draft" else sop.status
        db.commit()
        db.refresh(sop)
        return sop

    # ── 확정(Publish) ─────────────────────────────────────────

    def publish(self, db: Session, sop: SOP, publisher_id: int) -> SOP:
        """SOP 확정: draft/under_review → active, 버전 스냅샷 저장, RAG 인덱싱, 알림"""
        # 버전 스냅샷 저장 (SOP-F30)
        snapshot = {
            "title": sop.title,
            "steps": sop.steps,
            "checklist_items": sop.checklist_items,
            "cautions": sop.cautions,
            "version": sop.version,
        }
        history = SOPVersionHistory(
            sop_id=sop.id,
            version=sop.version,
            snapshot=snapshot,
            changed_by=publisher_id,
            change_summary="최초 확정",
        )
        db.add(history)

        sop.status = "active"
        sop.review_required = False
        sop.published_by = publisher_id
        sop.published_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(sop)

        # RAG 인덱싱 (비동기 태스크로 위임)
        try:
            from app.tasks.sop_tasks import ingest_sop_task
            ingest_sop_task.delay(sop.id)
        except Exception as exc:
            logger.warning("RAG 인덱싱 태스크 큐 실패 (무시): %s", exc)

        logger.info("SOP 확정 완료 sop_id=%s", sop.id)
        return sop

    # ── 아카이브 ──────────────────────────────────────────────

    def archive(self, db: Session, sop: SOP, archived_by: int) -> SOP:
        sop.status = "archived"
        sop.updated_by = archived_by
        db.commit()
        db.refresh(sop)
        return sop

    # ── 새 버전 ───────────────────────────────────────────────

    def create_new_version(
        self,
        db: Session,
        sop: SOP,
        file_path: str,
        file_type: str,
        updated_by: int,
    ) -> SOP:
        """기존 버전 스냅샷 저장 후 신규 버전 처리"""
        # 현재 버전 스냅샷 보관
        old_snapshot = {
            "title": sop.title,
            "steps": sop.steps,
            "checklist_items": sop.checklist_items,
            "cautions": sop.cautions,
            "version": sop.version,
        }
        db.add(SOPVersionHistory(
            sop_id=sop.id,
            version=sop.version,
            snapshot=old_snapshot,
            changed_by=updated_by,
            change_summary="신규 버전 생성으로 인한 이전 버전 보관",
        ))

        # 버전 번호 증가 (예: "1.0" → "2.0")
        try:
            major = int(sop.version.split(".")[0]) + 1
            new_version = f"{major}.0"
        except ValueError:
            new_version = "2.0"

        # 새 파일 재처리
        new_sop = self.process_upload(db, file_path, file_type, sop.department_id, updated_by)

        # 기존 SOP ID 유지하며 내용 교체
        sop.title = new_sop.title
        sop.steps = new_sop.steps
        sop.checklist_items = new_sop.checklist_items
        sop.cautions = new_sop.cautions
        sop.version = new_version
        sop.status = "draft"
        sop.review_required = new_sop.review_required
        sop.extraction_confidence = new_sop.extraction_confidence
        sop.ocr_confidence = new_sop.ocr_confidence
        sop.source_file = file_path
        sop.updated_by = updated_by

        # 임시 SOP 레코드 삭제
        db.delete(new_sop)
        db.commit()
        db.refresh(sop)
        return sop

    # ── Acknowledge ───────────────────────────────────────────

    def acknowledge(self, db: Session, sop: SOP, user_id: int) -> SOPAcknowledgement:
        """직원 SOP 확인 처리 (중복 방지)"""
        existing = (
            db.query(SOPAcknowledgement)
            .filter_by(sop_id=sop.id, version=sop.version, user_id=user_id)
            .first()
        )
        if existing:
            return existing

        ack = SOPAcknowledgement(sop_id=sop.id, version=sop.version, user_id=user_id)
        db.add(ack)
        db.commit()
        db.refresh(ack)
        return ack

    def get_acknowledge_stats(self, db: Session, sop: SOP) -> dict:
        """부서 내 Acknowledge 완료율 집계"""
        from app.database.models import User as UserModel

        dept_users = (
            db.query(UserModel)
            .filter_by(department_id=sop.department_id, is_active=True)
            .all()
        )
        acked = (
            db.query(SOPAcknowledgement)
            .filter_by(sop_id=sop.id, version=sop.version)
            .all()
        )
        acked_ids = {a.user_id for a in acked}
        total = len(dept_users)
        done = len([u for u in dept_users if u.id in acked_ids])

        return {
            "total_staff": total,
            "acknowledged": done,
            "pending": total - done,
            "completion_rate": round(done / total, 2) if total else 0.0,
        }
