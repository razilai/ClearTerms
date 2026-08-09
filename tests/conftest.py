"""Shared pytest fixtures.

Run from backend/ so the editable install resolves `app`:

    uv run --project backend pytest

Tests run against a real PostgreSQL database in a throwaway container
(testcontainers), matching production — no SQLite, so dialect differences (FK
enforcement, type semantics) can't hide until runtime. One container is started
per test session; the schema is built once from the ORM metadata. Per-test
isolation comes from wrapping every test in an outer transaction that is always
rolled back, so tests never see each other's rows and the schema is never rebuilt.

The `session` fixture yields a session bound to that transaction; the `client`
fixture overrides `app.db.engine.get_session` to hand every request that same
session, so writes a request flushes stay visible to later requests in the test
without needing a commit (the app's repos flush; get_session owns the commit).
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from app.agent import classifier
from app.core import storage as storage_module
from app.core.config import settings
from app.db import engine as engine_module
from app.main import app

# Importing Base from app.models (rather than app.models.base) also registers
# every table on Base.metadata, which create_all below depends on.
from app.models import Base

# Every tier hits a real agent — no fakes — against a tiny instruct model, so a
# full run stays under a minute. The `slow` tier (tests/system.py) runs against
# settings.agent_model directly (rather than this override) to prove whatever the
# configured production model is still works end to end. Override with
# CLEARTERMS_TEST_AGENT_MODEL if you prefer another small model you already have
# pulled.
LIGHT_MODEL = os.environ.get("CLEARTERMS_TEST_AGENT_MODEL", "qwen2.5:0.5b")


@pytest.fixture(autouse=True)
def light_agent(request: pytest.FixtureRequest) -> Iterator[None]:
    """Point the agent at a small, fast model for every non-``slow`` test.

    ``slow`` tests opt out and run against the production ``settings.agent_model``
    so the real model stays covered. ``build_agent`` is ``lru_cache``d and reads
    the model name once, so the cache is cleared around the override to force a
    rebuild against the right model.
    """
    if request.node.get_closest_marker("slow"):
        yield
        return
    original_model = settings.agent_model
    original_version = settings.model_version
    settings.agent_model = LIGHT_MODEL
    settings.model_version = f"test-{LIGHT_MODEL}"
    classifier.build_agent.cache_clear()
    try:
        yield
    finally:
        settings.agent_model = original_model
        settings.model_version = original_version
        classifier.build_agent.cache_clear()


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """One Postgres container for the whole session, schema created once.

    A sync fixture: it drives async setup through a throwaway ``asyncio.run`` so
    it doesn't pin an event loop that the (function-scoped) async fixtures would
    then have to share — every engine below is created and used within a single
    loop, which asyncpg requires.
    """
    with PostgresContainer("postgres:16", driver="asyncpg") as pg:
        url = pg.get_connection_url()

        async def _create_schema() -> None:
            engine = create_async_engine(url)
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
            finally:
                await engine.dispose()

        asyncio.run(_create_schema())
        yield url


@pytest_asyncio.fixture
async def db_connection(postgres_url: str) -> AsyncIterator[AsyncConnection]:
    """A connection inside an outer transaction that is always rolled back.

    This is the per-test isolation boundary: sessions below bind to this
    connection with ``join_transaction_mode="create_savepoint"``, so their
    commits land on savepoints within this transaction and the final rollback
    wipes everything the test wrote. The schema (created once per session)
    survives because it was committed before this transaction began.
    """
    engine = create_async_engine(postgres_url)
    conn = await engine.connect()
    trans = await conn.begin()
    try:
        yield conn
    finally:
        await trans.rollback()
        await conn.close()
        await engine.dispose()


async def session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """An AsyncSession bound to the per-test transaction (rolled back at teardown)."""
    factory = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    async with factory() as s:
        yield s


@pytest_asyncio.fixture
async def client(
    session: AsyncSession, db_connection: AsyncConnection
) -> AsyncIterator[httpx.AsyncClient]:
    from app.db.engine import get_session
    from app.main import app
    from app.services.queue import queue

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    # httpx.ASGITransport does not run FastAPI's lifespan, so nothing else
    # starts the queue for these tests. The worker opens its own session, so it
    # binds to the same per-test db_connection (savepoint mode) as `session`: a
    # worker's committed writes land on a shared savepoint the test can see, and
    # the outer-transaction rollback at teardown still discards everything.
    worker_factory = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    await queue.start(worker_factory, workers=1)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await queue.stop()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def committing_client(
    db_connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """A client whose requests each get a fresh session from the real get_session.

    The `client` fixture above cannot test the request transaction boundary: it
    overrides get_session to hand every request one long-lived session, so a
    flush in request A is visible to request B whether or not anything ever
    commits. This fixture deliberately leaves get_session alone and gives each
    request its own session, so data only crosses a request boundary if
    get_session actually commits.

    Every session binds to the one per-test ``db_connection`` (via the patched
    SessionFactory), so a real commit in request A lands on a savepoint the whole
    connection shares and is visible to request B — while the outer transaction's
    rollback at teardown still discards it all. get_session resolves
    SessionFactory as a module global on each call, so patching the attribute is
    enough.
    """
    monkeypatch.setattr(
        engine_module,
        "SessionFactory",
        async_sessionmaker(
            bind=db_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ),
    )

    # No dependency_overrides entry: the real, committing get_session is the
    # thing under test. Assert it, so a leaked override from another fixture
    # cannot silently turn this back into the shared-session setup.
    assert engine_module.get_session not in app.dependency_overrides

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def signup_headers(
    client: httpx.AsyncClient, email: str, password: str = "hunter2!"
) -> dict[str, str]:
    resp = await client.post(
        "/auth/signup", json={"email": email, "password": password}
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    return await signup_headers(client, "alice@example.com")


@pytest.fixture(autouse=True)
def fake_storage() -> Iterator[dict[str, bytes]]:
    """Replace object storage with an in-memory dict for every test.

    Tests that need to assert on stored objects can access ``fake_store`` by
    adding ``fake_storage`` to their parameter list. The store is cleared between
    tests because the fixture is function-scoped.
    """
    from app.services import media as media_module

    store: dict[str, bytes] = {}
    storage_module.set_fake_store(store)

    # Async processor stub: marks the attachment ready with placeholder keys.
    # Must be async so it can be awaited inside the existing event loop in tests;
    # asyncio.run() would fail with "loop already running".
    async def _fake_process(attachment_id: int) -> None:
        from app.db.engine import SessionFactory
        from app.db.repos import attachments as attachments_repo

        async with SessionFactory() as session:
            a = await attachments_repo.get(session, attachment_id)
            if a is None:
                return
            display_key = f"attachments/{attachment_id}/display.webp"
            thumb_key = f"attachments/{attachment_id}/thumb.webp"
            store[display_key] = b"fake-display"
            store[thumb_key] = b"fake-thumb"
            await attachments_repo.set_ready(
                session,
                attachment_id,
                display_key=display_key,
                thumbnail_key=thumb_key,
                width=640,
                height=480,
                duration_seconds=None,
            )
            await session.commit()

    media_module.set_processor(_fake_process)
    try:
        yield store
    finally:
        storage_module.set_fake_store(None)
        media_module.set_processor(None)


@pytest_asyncio.fixture
async def file_session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory over a real SQLite *file*, one connection per session.

    The `session` fixture's in-memory StaticPool hands every session the same
    DBAPI connection, so a worker "opening its own session" would silently share
    the caller's transaction — hiding exactly the cross-session behaviour the
    queue has to get right. A file-backed database gives real isolation.

    WAL mode + a busy timeout mirror app.db.engine.init_db, which turns WAL on
    for the production database. Without them this fixture diverges from
    production: a second concurrent writer fails outright with "database is
    locked" (SQLite's default rollback-journal mode has no wait semantics)
    instead of serialising behind the first writer and then hitting the unique
    constraint — the case get-or-create's IntegrityError recovery is written
    for. WAL still allows only one writer at a time; the busy timeout is what
    turns "fail immediately" into "wait, then proceed," so both are needed.
    """
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/queue.db",
        connect_args={"timeout": 30},
    )
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
