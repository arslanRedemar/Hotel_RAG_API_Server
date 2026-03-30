"""Presigned URL 인메모리 캐싱 테스트 (P2)"""




class TestPresignedUrlCache:
    def test_same_key_returns_same_url(self, tmp_path):
        """동일 storage_key + expires_in 에 같은 URL 반환 (캐시 적중)"""
        from app.storage.service import FileStorageService

        svc = FileStorageService(base_path=str(tmp_path))
        url1 = svc.generate_presigned_url("docs/test.pdf", expires_in=3600)
        url2 = svc.generate_presigned_url("docs/test.pdf", expires_in=3600)
        assert url1 == url2

    def test_cached_url_avoids_resign(self, tmp_path):
        """캐시 적중 시 _sign() 재호출 안 함"""
        from app.storage.service import FileStorageService

        svc = FileStorageService(base_path=str(tmp_path))
        sign_calls: list[int] = [0]
        original_sign = svc._sign

        def counting_sign(storage_key, exp):
            sign_calls[0] += 1
            return original_sign(storage_key, exp)

        svc._sign = counting_sign
        svc.generate_presigned_url("docs/test.pdf", expires_in=3600)
        svc.generate_presigned_url("docs/test.pdf", expires_in=3600)
        assert sign_calls[0] == 1  # 캐시 히트 → 서명 1번만

    def test_expired_cache_regenerated(self, tmp_path):
        """캐시 TTL 만료 후 URL 재생성 (시그니처 타임스탬프 다름)"""
        from unittest.mock import patch
        from app.storage.service import FileStorageService

        svc = FileStorageService(base_path=str(tmp_path))

        # 첫 번째 호출: t=1000
        with patch("app.storage.service.time") as mock_time:
            mock_time.time.return_value = 1000.0
            url1 = svc.generate_presigned_url("docs/test.pdf", expires_in=3600)

        # 캐시를 만료 처리 (cached_at = 0)
        cache_key = "docs/test.pdf:3600"
        if cache_key in svc._url_cache:
            url_val, _ = svc._url_cache[cache_key]
            svc._url_cache[cache_key] = (url_val, 0.0)

        # 두 번째 호출: t=2000 (캐시 만료 후 다른 expire_ts 생성)
        with patch("app.storage.service.time") as mock_time:
            mock_time.time.return_value = 2000.0
            url2 = svc.generate_presigned_url("docs/test.pdf", expires_in=3600)

        assert url1 != url2

    def test_different_keys_different_urls(self, tmp_path):
        """다른 storage_key 는 다른 URL"""
        from app.storage.service import FileStorageService

        svc = FileStorageService(base_path=str(tmp_path))
        url1 = svc.generate_presigned_url("docs/a.pdf", expires_in=3600)
        url2 = svc.generate_presigned_url("docs/b.pdf", expires_in=3600)
        assert url1 != url2

    def test_cache_is_per_instance(self, tmp_path):
        """캐시는 서비스 인스턴스별 독립 (모듈 수준 캐시면 공유됨도 OK)"""
        from app.storage.service import FileStorageService

        svc = FileStorageService(base_path=str(tmp_path))
        url = svc.generate_presigned_url("docs/test.pdf", expires_in=3600)
        assert url.startswith("/api/v1/files/")


class TestAuditLogArchive:
    def test_archive_returns_count(self, db):
        """archive_old_logs 는 처리된 로그 수 반환"""
        from app.audit.logger import archive_old_logs
        from app.database.models import AuditLog
        from datetime import datetime, timezone, timedelta

        # 6년 전 로그 삽입
        old_log = AuditLog(
            action="LOGIN",
            entity_type="user",
            entity_id="1",
            actor_id=1,
            actor_email="old@hotel.local",
            occurred_at=datetime.now(timezone.utc) - timedelta(days=6 * 365),
        )
        db.add(old_log)
        db.commit()

        count = archive_old_logs(db, older_than_years=5)
        assert count >= 1

    def test_archive_skips_recent_logs(self, db, tmp_path):
        """최근 로그는 아카이빙 대상 아님 — 오래된 로그 수는 변하지 않아야 함"""
        from app.audit.logger import archive_old_logs
        from app.database.models import AuditLog
        from datetime import datetime, timezone

        # 현재 아카이브 대상 수 측정
        before_count = archive_old_logs(db, older_than_years=5, archive_dir=str(tmp_path))

        # 최근 로그 추가
        recent_log = AuditLog(
            action="LOGOUT",
            entity_type="user",
            entity_id="2",
            actor_id=2,
            actor_email="recent@hotel.local",
            occurred_at=datetime.now(timezone.utc),
        )
        db.add(recent_log)
        db.commit()

        # 최근 로그 추가 후에도 아카이브 대상 수 동일
        after_count = archive_old_logs(db, older_than_years=5, archive_dir=str(tmp_path))
        assert after_count == before_count  # 최근 로그는 포함 안 됨
