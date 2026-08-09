"""Shared pytest fixtures.

Run from backend/ so the editable install resolves `app`:

    uv run --project backend pytest

Tests run against a real in-memory SQLite database (aiosqlite), not fakes.
The `session` fixture builds a fresh schema per test; the `client` fixture
overrides `app.db.engine.get_session` to hand every request that same session,
so writes a request flushes stay visible to later requests in the test without
needing a commit (the app's repos flush; the request transaction boundary is
not wired yet).
"""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agent import classifier
from app.core.config import settings

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


@pytest_asyncio.fixture
async def memory_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """In-memory SQLite on a StaticPool: every session shares one connection.

    That sharing is deliberate — it is what lets a request see writes an earlier
    request only flushed, and what makes a queue worker's session see the
    caller's data without a commit.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session(
    memory_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """An AsyncSession on a fresh in-memory SQLite DB, isolated per test.

    StaticPool keeps every checkout on one connection, so the ``:memory:``
    database survives across sessions within a single test instead of being
    dropped when a pooled connection is recycled.
    """
    async with memory_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(
    session: AsyncSession,
    memory_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    from app.db.engine import get_session
    from app.main import app
    from app.services.queue import queue

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    # httpx.ASGITransport does not run FastAPI's lifespan, so nothing else
    # starts the queue for these tests. Bound to memory_session_factory (the
    # same StaticPool connection as `session`) so a worker's writes land where
    # the test's client can see them, and every request through this client is
    # a real cache-miss-capable /analyze call, not just the tests that say so.
    await queue.start(memory_session_factory, workers=1)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        # try/finally, not a bare sequence: pytest throws a failing test's
        # exception into this generator at the `yield` above, so without this
        # both cleanup steps would be skipped — leaking a worker task bound to
        # a memory_session_factory whose engine gets disposed moments later.
        await queue.stop()
        app.dependency_overrides.clear()


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
