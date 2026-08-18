"""Unit tests: history repo and verdict recomputation."""


from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.categories import SCORE_AGGRESSIVE
from app.core.config import settings
from app.db.repos import documents, history, preferences, users
from app.models import Analysis, Document, User
from app.services import history as history_service
from tests.unit.factories import _items

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

    found = await history.list_for_user(session, alice.id, limit=50)
    assert {e.id for e in found} == {first.id, second.id}
    assert all(e.user_id == alice.id for e in found)


async def test_list_for_user_returns_empty_list_when_none(
    session: AsyncSession,
) -> None:
    user = await users.create(session, "ada@example.com", "pw1")

    assert await history.list_for_user(session, user.id, limit=50) == []


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

    found = await history.list_for_user(session, user.id, limit=50)
    assert [e.id for e in found] == [newest.id, middle.id, oldest.id]


# --- history verdict recomputation ------------------------------------------
#
# The stored HistoryEntry.verdict is a snapshot from analyze time. The list
# recomputes it against the user's *current* preferences so switching a
# category off retroactively updates old entries, matching what the detail
# view now hides. The stored value survives as the fallback for documents with
# no cached scores at the current model_version.


async def _analyzed_document(
    session: AsyncSession,
    text_hash: str,
    *,
    category: str = "arbitration",
    score: int = SCORE_AGGRESSIVE,
    model_version: str | None = None,
) -> Document:
    document = await documents.create(session, text_hash, None, "normalized text")
    session.add(
        Analysis(
            document_id=document.id,
            category=category,
            score=score,
            model_version=settings.model_version
            if model_version is None
            else model_version,
        )
    )
    await session.flush()
    return document


async def test_get_analyses_for_documents_groups_by_document(
    session: AsyncSession,
) -> None:
    first = await _analyzed_document(session, "hash-a")
    second = await _analyzed_document(session, "hash-b", category="liability")

    found = await documents.get_analyses_for_documents(
        session, [first.id, second.id], settings.model_version
    )
    assert {id_: [a.category for a in rows] for id_, rows in found.items()} == {
        first.id: ["arbitration"],
        second.id: ["liability"],
    }


async def test_get_analyses_for_documents_skips_other_model_versions(
    session: AsyncSession,
) -> None:
    document = await _analyzed_document(session, "hash-a", model_version="stale-v0")

    found = await documents.get_analyses_for_documents(
        session, [document.id], settings.model_version
    )
    assert found == {}


async def test_list_history_recomputes_verdict_from_current_preferences(
    session: AsyncSession,
) -> None:
    user = await users.create(session, "ada@example.com", "pw1")
    document = await _analyzed_document(session, "hash-a")
    await history.append(session, user.id, document.id, "down")
    await preferences.replace_for_user(
        session, user.id, _items(("arbitration", False))
    )

    page = await history_service.list_history(session, user.id, limit=50, cursor=None)
    assert [e.verdict for e in page.items] == ["up"]


async def test_list_history_falls_back_to_stored_verdict_without_cached_scores(
    session: AsyncSession,
) -> None:
    user = await users.create(session, "ada@example.com", "pw1")
    # Scores exist only under an older model_version, so there is nothing to
    # recompute from; the snapshot is the only honest answer.
    document = await _analyzed_document(session, "hash-a", model_version="stale-v0")
    await history.append(session, user.id, document.id, "down")

    page = await history_service.list_history(session, user.id, limit=50, cursor=None)
    assert [e.verdict for e in page.items] == ["down"]
