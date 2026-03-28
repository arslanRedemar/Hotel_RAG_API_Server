"""인증 모듈 단위 테스트"""

import pytest
from jose import JWTError

from app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    verify_access_token,
    verify_refresh_token,
)
from app.auth.password import hash_password, verify_password


class TestPassword:
    def test_hash_and_verify(self):
        plain = "Secret123!"
        hashed = hash_password(plain)
        assert hashed != plain
        assert verify_password(plain, hashed)

    def test_wrong_password_rejected(self):
        hashed = hash_password("correct")
        assert not verify_password("wrong", hashed)


class TestJWT:
    def test_access_token_roundtrip(self):
        token = create_access_token(user_id=1, email="a@b.com", role="staff")
        payload = verify_access_token(token)
        assert payload["sub"] == "1"
        assert payload["email"] == "a@b.com"
        assert payload["role"] == "staff"
        assert payload["type"] == "access"

    def test_refresh_token_roundtrip(self):
        token = create_refresh_token(user_id=42)
        payload = verify_refresh_token(token)
        assert payload["sub"] == "42"
        assert payload["type"] == "refresh"

    def test_access_token_rejected_as_refresh(self):
        token = create_access_token(user_id=1, email="a@b.com", role="staff")
        with pytest.raises(JWTError):
            verify_refresh_token(token)

    def test_refresh_token_rejected_as_access(self):
        token = create_refresh_token(user_id=1)
        with pytest.raises(JWTError):
            verify_access_token(token)

    def test_invalid_token_raises(self):
        with pytest.raises(JWTError):
            verify_access_token("not.a.valid.token")
