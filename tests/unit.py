"""Unit tests: auth helpers (hashing, JWT) and repo-level DB access.

No app, no fakes.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.repos import documents, history, preferences, users
from app.models import Analysis, Document, Finding, Preference, User
from app.schemas.preferences import PreferenceItem
from app.services import auth
from app.services.exceptions import InvalidTokenError, QueueFullError, QueueTimeoutError
from app.services.queue import AnalysisQueue


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
    findings: list[Finding] | None = None,
) -> Analysis:
    return Analysis(
        document_id=document_id,
        category=category,
        score=score,
        model_version=model_version,
        findings=[] if findings is None else findings,
    )


def _finding(evidence: str, *, score: int = 2, explanation: str = "why") -> Finding:
    """A Finding with no analysis_id — the relationship cascade fills it in."""
    return Finding(evidence=evidence, score=score, explanation=explanation)


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


async def test_create_document_duplicate_hash_returns_existing(
    session: AsyncSession,
) -> None:
    # Two concurrent analyses of the same TOS both miss the cache and reach
    # create(); ON CONFLICT makes the loser return the winner's row instead of
    # raising a unique violation. The loser's payload is dropped.
    first = await documents.create(session, "hash-a", None, "normalized text")
    second = await documents.create(session, "hash-a", None, "different text")

    assert second.id == first.id
    assert second.normalized_text == "normalized text"


async def test_save_and_get_analyses_round_trip(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    other = await documents.create(session, "hash-b", None, "other text")
    await documents.save_analyses(
        session,
        [
            _analysis(doc.id, "arbitration", score=2),
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


async def test_duplicate_analysis_returns_winner(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    first = await documents.save_analyses(
        session, [_analysis(doc.id, "arbitration", score=2)]
    )

    # A concurrent run persists the same (document_id, category, model_version)
    # first; the savepoint absorbs the composite-unique violation and the loser
    # gets back the winner's cached rows (score 2), not its own (score 5).
    second = await documents.save_analyses(
        session, [_analysis(doc.id, "arbitration", score=5)]
    )

    assert [a.score for a in first] == [2]
    assert [(a.category, a.score) for a in second] == [("arbitration", 2)]


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


# --- findings ---------------------------------------------------------------
#
# Findings are written and read through Analysis.findings; nothing addresses the
# table directly. expunge_all() before each read so the assertions go through a
# real query rather than the identity map handing back the objects just added.


async def test_save_analyses_cascades_findings_in_reported_order(
    session: AsyncSession,
) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    await documents.save_analyses(
        session,
        [
            _analysis(
                doc.id,
                "arbitration",
                score=2,
                findings=[
                    _finding("waive your right to a jury"),
                    _finding("class action waiver"),
                ],
            ),
            _analysis(doc.id, "liability", score=1, findings=[_finding("as is")]),
            # densify emits all six categories; absent ones carry no findings.
            _analysis(doc.id, "termination", score=0),
        ],
    )
    session.expunge_all()

    result = await documents.get_document_with_analyses(session, doc.id)
    assert result is not None
    _, analyses = result
    by_category = {a.category: a for a in analyses}

    # Grouped under the right parent at all == analysis_id was populated by the
    # cascade; the order == the relationship's order_by held through the round
    # trip, which densify's contract depends on.
    assert [f.evidence for f in by_category["arbitration"].findings] == [
        "waive your right to a jury",
        "class action waiver",
    ]
    assert [f.evidence for f in by_category["liability"].findings] == ["as is"]
    assert by_category["termination"].findings == []


async def test_get_analyses_leaves_findings_unloaded(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    await documents.save_analyses(
        session,
        [_analysis(doc.id, "arbitration", score=2, findings=[_finding("jury waiver")])],
    )
    session.expunge_all()

    found = await documents.get_analyses(session, doc.id, MODEL_V1)
    # lazy="raise": the verdict path needs scores only, so reaching for findings
    # here is an error rather than a silent query per category.
    with pytest.raises(InvalidRequestError):
        _ = found[0].findings


async def test_deleting_an_analysis_deletes_its_findings(session: AsyncSession) -> None:
    doc = await documents.create(session, "hash-a", None, "normalized text")
    await documents.save_analyses(
        session,
        [_analysis(doc.id, "arbitration", score=2, findings=[_finding("jury waiver")])],
    )
    session.expunge_all()

    result = await documents.get_document_with_analyses(session, doc.id)
    assert result is not None
    _, analyses = result
    await session.delete(analyses[0])
    await session.flush()

    # delete-orphan cascades in Python, so this holds without SQLite's
    # PRAGMA foreign_keys=ON, which the app never sets.
    remaining = await session.execute(select(Finding))
    assert remaining.scalars().all() == []


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


# --- analysis queue ----------------------------------------------------------
#
# The `session` fixture's StaticPool hands every session the same DBAPI
# connection, which would hide the cross-session behaviour under test here.
# These use `file_session_factory` (a real SQLite file, one connection per
# session) so the worker's session is genuinely independent of the caller's.


async def test_submit_runs_the_job_and_returns_its_result(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    try:

        async def job(session: AsyncSession) -> str:
            return "done"

        assert await q.submit(user_id=1, job=job) == "done"
    finally:
        await q.stop()


async def test_worker_gives_the_job_a_live_session_the_caller_does_not_own(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The job's session must be usable and must not be the caller's."""
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    try:
        async with file_session_factory() as caller_session:

            async def job(session: AsyncSession) -> bool:
                # Usable: a real query runs against it.
                await session.execute(select(User))
                return session is not caller_session

            assert await q.submit(user_id=1, job=job) is True
    finally:
        await q.stop()


async def test_worker_commits_the_job_session(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Writes a job makes are durable without the caller committing anything."""
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    try:

        async def job(session: AsyncSession) -> None:
            session.add(User(email="queued@example.com", password_hash="x"))

        await q.submit(user_id=1, job=job)
    finally:
        await q.stop()

    async with file_session_factory() as verify:
        found = await verify.execute(
            select(User).where(User.email == "queued@example.com")
        )
        assert found.scalar_one_or_none() is not None


async def test_job_exception_propagates_to_the_caller(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    try:

        async def job(session: AsyncSession) -> None:
            raise ValueError("job blew up")

        with pytest.raises(ValueError, match="job blew up"):
            await q.submit(user_id=1, job=job)

        # The worker survives a failed job and keeps serving.
        async def ok(session: AsyncSession) -> str:
            return "still alive"

        assert await q.submit(user_id=1, job=ok) == "still alive"
    finally:
        await q.stop()


async def test_single_worker_runs_one_job_at_a_time(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    running = 0
    peak = 0
    try:

        async def job(session: AsyncSession) -> None:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.05)
            running -= 1

        await asyncio.gather(*(q.submit(user_id=i, job=job) for i in range(5)))
    finally:
        await q.stop()

    assert peak == 1


async def test_two_workers_run_two_jobs_at_a_time(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=2)
    running = 0
    peak = 0
    try:

        async def job(session: AsyncSession) -> None:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.05)
            running -= 1

        await asyncio.gather(*(q.submit(user_id=i, job=job) for i in range(6)))
    finally:
        await q.stop()

    assert peak == 2


async def test_jobs_from_one_user_run_in_submission_order(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Same user, same priority -> FIFO. Proves the tie-break is stable."""
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    order: list[int] = []
    try:

        def make(n: int) -> Callable[[AsyncSession], Awaitable[None]]:
            async def job(session: AsyncSession) -> None:
                order.append(n)

            return job

        await asyncio.gather(*(q.submit(user_id=7, job=make(n)) for n in range(5)))
    finally:
        await q.stop()

    assert order == [0, 1, 2, 3, 4]


async def test_stop_cancels_workers(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=2)
    await q.stop()
    assert q._workers == []


async def test_submit_raises_when_the_queue_is_full(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1, maxsize=1)
    release = asyncio.Event()
    try:

        async def blocker(session: AsyncSession) -> None:
            await release.wait()

        # One job occupies the worker, one fills the single queue slot. The
        # two submissions are staggered with an intervening await: creating
        # both back-to-back schedules them in the same event-loop tick, and
        # the worker's wakeup (queued via the first put_nowait) is itself
        # deferred to the *next* tick — so an unstaggered second submission
        # can race the worker for the one slot and get rejected instead of
        # the third.
        first = asyncio.create_task(q.submit(user_id=1, job=blocker))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(q.submit(user_id=2, job=blocker))
        await asyncio.sleep(0.05)

        with pytest.raises(QueueFullError):
            await q.submit(user_id=3, job=blocker)

        release.set()
        await asyncio.gather(first, second)
    finally:
        release.set()
        await q.stop()


async def test_submit_raises_when_the_wait_exceeds_the_timeout(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1, timeout=0.05)
    release = asyncio.Event()
    try:

        async def blocker(session: AsyncSession) -> None:
            await release.wait()

        first = asyncio.create_task(q.submit(user_id=1, job=blocker))
        await asyncio.sleep(0.01)

        async def quick(session: AsyncSession) -> str:
            return "never seen"

        with pytest.raises(QueueTimeoutError):
            await q.submit(user_id=2, job=quick)

        release.set()
        # first's own caller-side wait times out too: it has been waiting
        # since before the initial sleep, so its 0.05s deadline elapses
        # before the second submission's later deadline does — the timeout
        # applies uniformly to every caller, not just ones still queued.
        with pytest.raises(QueueTimeoutError):
            await first
    finally:
        release.set()
        await q.stop()


async def test_timed_out_job_still_runs_and_still_caches(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Giving up on the wait must not throw away the work already queued."""
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1, timeout=0.05)
    release = asyncio.Event()
    ran = asyncio.Event()
    try:

        async def blocker(session: AsyncSession) -> None:
            await release.wait()

        async def later(session: AsyncSession) -> None:
            ran.set()

        first = asyncio.create_task(q.submit(user_id=1, job=blocker))
        await asyncio.sleep(0.01)

        with pytest.raises(QueueTimeoutError):
            await q.submit(user_id=2, job=later)

        release.set()
        # first's own caller-side wait times out too, same reasoning as
        # above — its deadline elapses before release.set() is even called.
        # The job itself (blocker) keeps running regardless (shielded); it
        # is the later job's persistence past its own caller's timeout that
        # this test is really about.
        with pytest.raises(QueueTimeoutError):
            await first
        await asyncio.wait_for(ran.wait(), timeout=1.0)
    finally:
        release.set()
        await q.stop()


async def test_submit_returns_the_result_when_it_finishes_within_the_timeout(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The normal path: a caller waits under wait_for/shield and gets the
    job's actual return value back, not a timeout.

    timeout=1.0 vs. a ~0.02s job is a ~50x margin — comfortably deterministic
    on any machine this suite runs on, rather than tuned close to the edge
    the way the two timeout tests above deliberately are.
    """
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1, timeout=1.0)
    try:

        async def job(session: AsyncSession) -> str:
            await asyncio.sleep(0.02)
            return "the real result"

        assert await q.submit(user_id=1, job=job) == "the real result"
    finally:
        await q.stop()


async def test_a_new_users_first_job_beats_a_busy_users_backlog(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    order: list[str] = []
    release = asyncio.Event()
    try:

        def make(label: str) -> Callable[[AsyncSession], Awaitable[None]]:
            async def job(session: AsyncSession) -> None:
                order.append(label)

            return job

        async def blocker(session: AsyncSession) -> None:
            await release.wait()

        # Occupy the single worker so everything else genuinely queues up.
        held = asyncio.create_task(q.submit(user_id=99, job=blocker))
        await asyncio.sleep(0.05)

        # Alice piles up four documents, then Bob submits one.
        alice = [
            asyncio.create_task(q.submit(user_id=1, job=make(f"alice{n}")))
            for n in range(4)
        ]
        await asyncio.sleep(0.05)
        bob = asyncio.create_task(q.submit(user_id=2, job=make("bob0")))
        await asyncio.sleep(0.05)

        release.set()
        await asyncio.gather(held, bob, *alice)
    finally:
        release.set()
        await q.stop()

    # Alice's first job was already at priority 0 before Bob arrived, so it
    # keeps its place; Bob's single job then beats alice1..alice3.
    assert order[0] == "alice0"
    assert order[1] == "bob0"
    assert order[2:] == ["alice1", "alice2", "alice3"]


async def test_pending_counter_returns_to_zero_after_jobs_finish(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A leaked counter would permanently deprioritise the user."""
    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    try:

        async def ok(session: AsyncSession) -> None:
            return None

        async def boom(session: AsyncSession) -> None:
            raise ValueError("nope")

        await q.submit(user_id=5, job=ok)
        with pytest.raises(ValueError):
            await q.submit(user_id=5, job=boom)
    finally:
        await q.stop()

    assert q._pending == {}


async def test_rejected_submission_does_not_leak_the_pending_counter(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A QueueFullError never reaches a worker, so it must not have counted."""
    q = AnalysisQueue()
    # maxsize=1, not 0 — asyncio.Queue treats maxsize=0 as *unbounded*.
    await q.start(file_session_factory, workers=1, maxsize=1)
    release = asyncio.Event()
    try:

        async def blocker(session: AsyncSession) -> None:
            await release.wait()

        # Staggered with an intervening await, matching
        # test_submit_raises_when_the_queue_is_full above: creating both
        # back-to-back schedules them in the same event-loop tick, and the
        # worker's wakeup (queued via the first put_nowait) is itself
        # deferred to the *next* tick — so an unstaggered second submission
        # can race the worker for the one slot and get rejected instead of
        # the third.
        first = asyncio.create_task(q.submit(user_id=5, job=blocker))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(q.submit(user_id=5, job=blocker))
        await asyncio.sleep(0.05)

        with pytest.raises(QueueFullError):
            await q.submit(user_id=5, job=blocker)

        release.set()
        await asyncio.gather(first, second)
    finally:
        release.set()
        await q.stop()

    assert q._pending == {}


# --- analysis pipeline: get_or_create_document + queue wiring ---------------


async def test_get_or_create_document_is_idempotent(session: AsyncSession) -> None:
    from app.services.analysis import get_or_create_document

    first = await get_or_create_document(
        session, "hash-abc", "https://example.com/tos", "normalized", "Original"
    )
    second = await get_or_create_document(
        session, "hash-abc", "https://example.com/tos", "normalized", "Original"
    )
    assert first.id == second.id


async def test_analyze_issues_no_write_before_submitting(
    file_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller must have issued no write by the time it parks on the queue.

    Holding an *uncommitted write* across the wait is the defect this task
    removes: on SQLite that is the global write lock, on Postgres a row lock on
    documents.text_hash plus a pooled connection held for the whole wait.

    Deliberately NOT asserted via `session.in_transaction()`: SQLAlchemy
    autobegins a transaction on the first SELECT, so that flag is True after a
    harmless read and would be testing the wrong thing.
    """
    from sqlalchemy import event

    from app.services import analysis as analysis_service
    from app.services.queue import AnalysisQueue

    q = AnalysisQueue()
    await q.start(file_session_factory, workers=1)
    statements: list[str] = []
    writes_at_submit: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    engine = file_session_factory.kw["bind"]
    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        async with file_session_factory() as caller:
            user = User(email="probe@example.com", password_hash="x")
            caller.add(user)
            await caller.commit()
            statements.clear()  # fixture setup is not under test

            class SpyQueue:
                async def submit(self, user_id: int, job: object) -> object:
                    writes_at_submit.extend(
                        s
                        for s in statements
                        if s.lstrip()
                        .upper()
                        .startswith(("INSERT", "UPDATE", "DELETE"))
                    )
                    return await q.submit(user_id, job)  # type: ignore[arg-type]

            # monkeypatch (not raw assignment) so the module singleton is
            # restored at teardown; a leaked patch would point every later test
            # at this dead queue.
            monkeypatch.setattr(analysis_service, "queue", SpyQueue())
            await analysis_service.analyze(
                caller, user.id, "Some terms of service text.", None
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)
        await q.stop()

    assert writes_at_submit == []


async def test_concurrent_jobs_for_the_same_text_share_one_document(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The get-or-create race: both jobs must land on one document row.

    Tested at the service layer, not over HTTP: the `client` fixture overrides
    `get_session` so every request in a test shares ONE AsyncSession, and
    AsyncSession is not safe for concurrent use by multiple tasks. Two
    concurrent HTTP requests would exercise an unsupported configuration rather
    than the race. Here each job gets a genuinely independent session, which is
    what production does.
    """
    from app.services.analysis import analyze_document_job

    async def run_job() -> int:
        async with file_session_factory() as session:
            document_id = await analyze_document_job(
                session,
                text_hash="race-hash",
                url=None,
                normalized_text="identical terms of service text.",
                original_text="Identical terms of service text.",
            )
            await session.commit()
            return document_id

    first, second = await asyncio.gather(run_job(), run_job())
    assert first == second

    async with file_session_factory() as verify:
        rows = await verify.execute(
            select(Document).where(Document.text_hash == "race-hash")
        )
        assert len(rows.scalars().all()) == 1
