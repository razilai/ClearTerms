"""Unit tests: pure auth functions (hashing, JWT). No app, no fakes."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import settings
from app.services import auth
from app.services.exceptions import InvalidTokenError


def _encode(claims: dict, *, secret: str | None = None, algorithm: str = "HS256") -> str:
    """Sign a JWT directly, bypassing auth.create_access_token's fixed claims."""
    key = settings.jwt_secret.get_secret_value() if secret is None else secret
    return jwt.encode(claims, key, algorithm=algorithm)


def _valid_claims(**overrides: object) -> dict:
    now = datetime.now(UTC)
    claims: dict = {
        "sub": "42",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return claims


def test_hash_verify_roundtrip() -> None:
    hashed = auth.hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert auth.verify_password("s3cret!", hashed)


def test_verify_wrong_password() -> None:
    hashed = auth.hash_password("s3cret!")
    assert not auth.verify_password("wrong", hashed)


def test_token_roundtrip() -> None:
    token = auth.create_access_token(42)
    decoded = auth.decode_access_token(token)
    assert decoded == 42
    # sub travels as a string in the JWT; decode must coerce it back to int.
    assert isinstance(decoded, int)


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


def test_token_missing_iat_rejected() -> None:
    claims = _valid_claims()
    del claims["iat"]
    with pytest.raises(InvalidTokenError):
        auth.decode_access_token(_encode(claims))


def test_token_missing_sub_rejected() -> None:
    claims = _valid_claims()
    del claims["sub"]
    with pytest.raises(InvalidTokenError):
        auth.decode_access_token(_encode(claims))


def test_alg_none_rejected() -> None:
    # Classic JWT downgrade attack: an unsigned "none"-alg token must not pass,
    # because decode pins algorithms=[HS256].
    token = jwt.encode(_valid_claims(), key="", algorithm="none")
    with pytest.raises(InvalidTokenError):
        auth.decode_access_token(token)


def test_wrong_secret_rejected() -> None:
    # Correctly formed and HS256-signed, but with a foreign key — signature fails.
    token = _encode(_valid_claims(), secret="not-the-real-secret")
    with pytest.raises(InvalidTokenError):
        auth.decode_access_token(token)


def test_non_numeric_sub_rejected() -> None:
    # Passes JWT's require/signature checks but fails TokenPayload coercion,
    # exercising the ValidationError branch in decode_access_token.
    token = _encode(_valid_claims(sub="not-an-int"))
    with pytest.raises(InvalidTokenError):
        auth.decode_access_token(token)
