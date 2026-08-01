"""Unit tests: pure auth functions (hashing, JWT). No app, no fakes."""

import jwt
import pytest

from app.core.config import settings
from app.services import auth
from app.services.exceptions import InvalidTokenError


def test_hash_verify_roundtrip() -> None:
    hashed = auth.hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert auth.verify_password("s3cret!", hashed)


def test_verify_wrong_password() -> None:
    hashed = auth.hash_password("s3cret!")
    assert not auth.verify_password("wrong", hashed)


def test_token_roundtrip() -> None:
    token = auth.create_access_token(42)
    assert auth.decode_access_token(token) == 42


def test_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "jwt_expire_minutes", -1)
    token = auth.create_access_token(42)
    with pytest.raises(InvalidTokenError):
        auth.decode_access_token(token)


def test_tampered_token() -> None:
    token = auth.create_access_token(42)
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(InvalidTokenError):
        auth.decode_access_token(tampered)


def test_garbage_token() -> None:
    with pytest.raises(InvalidTokenError):
        auth.decode_access_token("not-a-jwt")


def test_token_missing_exp_rejected() -> None:
    token = jwt.encode(
        {"sub": "42", "iat": 0},
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        auth.decode_access_token(token)
