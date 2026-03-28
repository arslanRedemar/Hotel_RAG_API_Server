"""파일 저장소 — 로컬 스토리지 (초기) / S3 호환 전환 가능"""

import hashlib
import hmac
import logging
import time
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings

logger = logging.getLogger(__name__)

ALLOWED_MIME: dict[str, str] = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "image/jpeg": "jpg",
    "image/png": "png",
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


class FileStorageService:
    def __init__(self, base_path: str | None = None):
        self.base_path = Path(base_path or settings.file_storage_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    # ── 업로드 ──────────────────────────────────────────────

    async def save(self, file: UploadFile, subfolder: str = "") -> dict:
        if file.content_type not in ALLOWED_MIME:
            raise ValueError(f"허용되지 않는 파일 형식: {file.content_type}")

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise ValueError("파일 크기가 50MB를 초과합니다")

        ext = ALLOWED_MIME[file.content_type]
        filename = f"{uuid.uuid4().hex}.{ext}"
        save_dir = self.base_path / subfolder
        save_dir.mkdir(parents=True, exist_ok=True)
        (save_dir / filename).write_bytes(content)

        storage_key = f"{subfolder}/{filename}" if subfolder else filename
        logger.info("파일 저장 완료", extra={"storage_key": storage_key})

        return {
            "storage_key": storage_key,
            "original_name": file.filename,
            "file_type": ext,
            "file_size_bytes": len(content),
        }

    # ── Presigned URL ────────────────────────────────────────

    def generate_presigned_url(self, storage_key: str, expires_in: int = 3600) -> str:
        expire_ts = int(time.time()) + expires_in
        sig = self._sign(storage_key, expire_ts)
        return f"/api/v1/files/{storage_key}?exp={expire_ts}&sig={sig}"

    def validate_presigned_url(self, storage_key: str, exp: int, sig: str) -> bool:
        if time.time() > exp:
            return False
        return hmac.compare_digest(sig, self._sign(storage_key, exp))

    def _sign(self, storage_key: str, exp: int) -> str:
        msg = f"{storage_key}:{exp}".encode()
        return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()[:16]

    # ── 소프트 삭제 ──────────────────────────────────────────

    def soft_delete(self, storage_key: str) -> None:
        src = self.base_path / storage_key
        if src.exists():
            dst = self.base_path / "deleted" / storage_key
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            logger.info("파일 소프트 삭제", extra={"storage_key": storage_key})

    def hard_delete(self, storage_key: str) -> None:
        """Celery 정리 태스크에서 호출 — 실제 파일 삭제."""
        target = self.base_path / "deleted" / storage_key
        if target.exists():
            target.unlink()
            logger.info("파일 영구 삭제", extra={"storage_key": storage_key})

    # ── 읽기 ────────────────────────────────────────────────

    def read_bytes(self, storage_key: str) -> bytes:
        return (self.base_path / storage_key).read_bytes()


file_storage = FileStorageService()
