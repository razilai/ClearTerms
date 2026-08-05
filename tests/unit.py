"""Unit tests: auth helpers (hashing, JWT) and repo-level DB access.

No app, no fakes.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.repos import documents, users
from app.models import Analysis
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


async def test_create_user_then_read_back(session: AsyncSession) -> None:
    created = await users.create(session, "ada@example.com", "hashed-pw")
    assert created.id is not None, "flush should populate the PK"

    found = await users.get_by_email(session, "ada@example.com")
    assert found is not None
    assert found.id == created.id
    assert found.email == "ada@example.com"
    assert found.password_hash == "hashed-pw"


async def test_get_by_email_returns_none_when_absent(session: AsyncSession) -> None:
    await users.create(session, "ada@example.com", "hashed-pw")

    assert await users.get_by_email(session, "nobody@example.com") is None


async def test_create_user_duplicate_email_raises(session: AsyncSession) -> None:
    await users.create(session, "ada@example.com", "hashed-pw")

    with pytest.raises(IntegrityError):
        await users.create(session, "ada@example.com", "another-pw")


async def test_create_multiple_users(session: AsyncSession) -> None:
    u1 = await users.create(session, "ada@example.com", "pw1")
    u2 = await users.create(session, "bob@example.com", "pw2")

    assert u1.id != u2.id
    assert await users.get_by_email(session, "ada@example.com") is not None
    assert await users.get_by_email(session, "bob@example.com") is not None


# --- documents repo ---------------------------------------------------------
#
# Category slugs are plain String(64) with no FK, so these use literals rather
# than importing the taxonomy: what is under test is filtering and constraints,
# not the label set.

MODEL_V1 = "test-model-v1"
MODEL_V2 = "test-model-v2"


def _analysis(
    document_id: int,
    category: str,
    *,
    score: int = 1,
    model_version: str = MODEL_V1,
    explanation: str | None = None,
) -> Analysis:
    return Analysis(
        document_id=document_id,
        category=category,
        score=score,
        model_version=model_version,
        explanation=explanation,
    )


async def test_get_by_hash_returns_document(session: AsyncSession) -> None:
    created = await documents.create(
        session, "hash-a", "https://example.test/tos", "normalized text"
    )

    found = await documents.get_by_hash(session, "hash-a")
    assert found is not None
    assert found.id == created.id
    assert found.url == "https://example.test/tos"
    assert found.normalized_text == "normalized text"


async def test_get_by_hash_returns_none_when_absent(session: AsyncSession) -> None:
    await documents.create(session, "hash-a", None, "normalized text")

    assert await documents.get_by_hash(session, "hash-missing") is None


async def test_create_document_populates_id(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")

    assert doc.id is not None, "flush should populate the PK"


async def test_create_document_duplicate_hash_raises(session: AsyncSession) -> None:
    await documents.create(session, "hash-a", None, "normalized text")

    with pytest.raises(IntegrityError):
        await documents.create(session, "hash-a", None, "different text")


async def test_save_and_get_analyses_round_trip(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    other = await documents.create(session, "hash-b", None, "other text")
    await documents.save_analyses(
        session,
        [
            _analysis(
                doc.id, "arbitration", score=2, explanation="binding arbitration"
            ),
            _analysis(doc.id, "data_collection", score=1),
            # Belongs to a different document; must not leak into doc's results.
            _analysis(other.id, "liability", score=2),
        ],
    )

    found = await documents.get_analyses(session, doc.id, MODEL_V1)
    assert {(a.category, a.score) for a in found} == {
        ("arbitration", 2),
        ("data_collection", 1),
    }
    assert all(a.document_id == doc.id for a in found)
    arbitration = next(a for a in found if a.category == "arbitration")
    assert arbitration.explanation == "binding arbitration"


async def test_get_analyses_filters_by_model_version(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    await documents.save_analyses(
        session,
        [
            _analysis(doc.id, "arbitration", score=2, model_version=MODEL_V1),
            _analysis(doc.id, "arbitration", score=0, model_version=MODEL_V2),
        ],
    )

    found = await documents.get_analyses(session, doc.id, MODEL_V1)
    assert [(a.model_version, a.score) for a in found] == [(MODEL_V1, 2)]


async def test_duplicate_analysis_raises(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    await documents.save_analyses(session, [_analysis(doc.id, "arbitration")])

    # Same (document_id, category, model_version) violates the composite unique.
    with pytest.raises(IntegrityError):
        await documents.save_analyses(session, [_analysis(doc.id, "arbitration")])


async def test_get_document_with_analyses(session: AsyncSession) -> None:
    doc = await documents.create(
        session, "hash-a", "https://example.test/tos", "normalized text"
    )
    await documents.save_analyses(
        session,
        [
            _analysis(doc.id, "arbitration", score=2),
            _analysis(doc.id, "liability", score=1),
        ],
    )

    result = await documents.get_document_with_analyses(session, doc.id)
    assert result is not None
    found_doc, found_analyses = result
    assert found_doc.id == doc.id
    assert found_doc.text_hash == "hash-a"
    assert {a.category for a in found_analyses} == {"arbitration", "liability"}


async def test_get_document_with_analyses_missing_returns_none(
    session: AsyncSession,
) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")

    assert await documents.get_document_with_analyses(session, doc.id + 1000) is None
