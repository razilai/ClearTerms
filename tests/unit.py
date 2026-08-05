"""Unit tests: auth helpers (hashing, JWT) and repo-level DB access.

No app, no fakes.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.repos import documents, history, preferences, users
from app.models import Analysis, Document, Preference, User
from app.schemas.preferences import PreferenceItem
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


# --- preferences repo -------------------------------------------------------
#
# Preference.user_id is a real FK, so these create actual users rather than
# inventing ids: the tests stay valid if FK enforcement is ever switched on.


def _preference(user_id: int, category: str, weight: float = 1.0) -> Preference:
    return Preference(user_id=user_id, category=category, weight=weight)


def _items(*pairs: tuple[str, float]) -> list[PreferenceItem]:
    return [PreferenceItem(category=c, weight=w) for c, w in pairs]


async def test_get_for_user_returns_only_that_users_preferences(
    session: AsyncSession,
) -> None:
    alice = await users.create(session, "ada@example.com", "pw1")
    bob = await users.create(session, "bob@example.com", "pw2")
    await preferences.replace_for_user(
        session, alice.id, _items(("arbitration", 1.0), ("liability", 0.5))
    )
    await preferences.replace_for_user(
        session, bob.id, _items(("data_collection", 2.0))
    )

    found = await preferences.get_for_user(session, alice.id)
    assert {(p.category, p.weight) for p in found} == {
        ("arbitration", 1.0),
        ("liability", 0.5),
    }
    assert all(p.user_id == alice.id for p in found)


async def test_get_for_user_returns_empty_list_when_none(session: AsyncSession) -> None:
    user = await users.create(session, "ada@example.com", "pw1")

    assert await preferences.get_for_user(session, user.id) == []


async def test_replace_for_user_sets_initial_preferences(session: AsyncSession) -> None:
    user = await users.create(session, "ada@example.com", "pw1")

    returned = await preferences.replace_for_user(
        session, user.id, _items(("arbitration", 1.0), ("liability", 0.5))
    )
    assert {(p.category, p.weight) for p in returned} == {
        ("arbitration", 1.0),
        ("liability", 0.5),
    }

    found = await preferences.get_for_user(session, user.id)
    assert {(p.category, p.weight) for p in found} == {
        ("arbitration", 1.0),
        ("liability", 0.5),
    }


async def test_replace_for_user_wipes_previous_set(session: AsyncSession) -> None:
    user = await users.create(session, "ada@example.com", "pw1")
    other = await users.create(session, "bob@example.com", "pw2")
    await preferences.replace_for_user(
        session, user.id, _items(("arbitration", 1.0), ("liability", 0.5))
    )
    await preferences.replace_for_user(session, other.id, _items(("arbitration", 9.0)))

    await preferences.replace_for_user(
        session, user.id, _items(("data_collection", 2.0), ("termination", 1.5))
    )

    found = await preferences.get_for_user(session, user.id)
    assert {(p.category, p.weight) for p in found} == {
        ("data_collection", 2.0),
        ("termination", 1.5),
    }
    # The replaced categories are gone entirely, not merely re-weighted.
    assert {p.category for p in found}.isdisjoint({"arbitration", "liability"})
    # The wipe is scoped to one user: bob keeps his own "arbitration" row.
    other_found = await preferences.get_for_user(session, other.id)
    assert {(p.category, p.weight) for p in other_found} == {("arbitration", 9.0)}


async def test_duplicate_category_for_user_raises(session: AsyncSession) -> None:
    user = await users.create(session, "ada@example.com", "pw1")
    await preferences.replace_for_user(session, user.id, _items(("arbitration", 1.0)))

    # Added directly rather than through the repo: this pins the DB constraint
    # itself, leaving replace_for_user free to dedupe its own input if it wants.
    session.add(_preference(user.id, "arbitration", weight=2.0))
    with pytest.raises(IntegrityError):
        await session.flush()


# --- history repo -----------------------------------------------------------


async def _user_and_document(
    session: AsyncSession,
    email: str = "ada@example.com",
    text_hash: str = "hash-a",
) -> tuple[User, Document]:
    """Real rows for HistoryEntry's two FKs."""
    user = await users.create(session, email, "pw1")
    document = await documents.create(session, text_hash, None, "normalized text")
    return user, document


async def test_append_creates_entry(session: AsyncSession) -> None:
    user, doc = await _user_and_document(session)

    entry = await history.append(session, user.id, doc.id, "down")

    assert entry.id is not None, "flush should populate the PK"
    assert entry.user_id == user.id
    assert entry.document_id == doc.id
    assert entry.verdict == "down"


async def test_list_for_user_returns_only_that_users_entries(
    session: AsyncSession,
) -> None:
    alice = await users.create(session, "ada@example.com", "pw1")
    bob = await users.create(session, "bob@example.com", "pw2")
    doc = await documents.create(session, "hash-a", None, "normalized text")

    first = await history.append(session, alice.id, doc.id, "down")
    second = await history.append(session, alice.id, doc.id, "up")
    await history.append(session, bob.id, doc.id, "up")

    found = await history.list_for_user(session, alice.id)
    assert {e.id for e in found} == {first.id, second.id}
    assert all(e.user_id == alice.id for e in found)


async def test_list_for_user_returns_empty_list_when_none(
    session: AsyncSession,
) -> None:
    user = await users.create(session, "ada@example.com", "pw1")

    assert await history.list_for_user(session, user.id) == []


async def test_list_for_user_orders_newest_first(session: AsyncSession) -> None:
    user, doc = await _user_and_document(session)
    middle = await history.append(session, user.id, doc.id, "down")
    newest = await history.append(session, user.id, doc.id, "up")
    oldest = await history.append(session, user.id, doc.id, "down")

    # created_at is a server_default of CURRENT_TIMESTAMP, which SQLite resolves
    # to whole seconds — rows appended in one test would otherwise share a
    # timestamp and leave the ordering undefined. Assigning explicitly also puts
    # created_at order deliberately out of step with insertion order, so this
    # pins ordering by created_at rather than by id.
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    oldest.created_at = base
    middle.created_at = base + timedelta(minutes=5)
    newest.created_at = base + timedelta(minutes=10)
    await session.flush()

    found = await history.list_for_user(session, user.id)
    assert [e.id for e in found] == [newest.id, middle.id, oldest.id]
