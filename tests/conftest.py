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
from app.core.config import settings
from app.db import engine as engine_module
from app.main import app

# Importing Base from app.models (rather than app.models.base) also registers
# every table on Base.metadata, which create_all below depends on.
from app.models import Base

# The production model (qwen3:4b) is a thinking model: minutes per call on a
# laptop CPU. The default tiers still hit a real agent — no fakes — but against
# a tiny instruct model, so a full run stays under a minute. The `slow` tier
# (tests/system.py) keeps exercising settings.agent_model to prove the real
# model still works. Override with CLEARTERMS_TEST_AGENT_MODEL if you prefer
# another small model you already have pulled.
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


@pytest_asyncio.fixture
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
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    from app.db.engine import get_session
    from app.main import app

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
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
