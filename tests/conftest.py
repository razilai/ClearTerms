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

import httpx
import pytest
import pytest_asyncio
from app.agent import classifier
from app.core.config import settings
from app.db import engine as engine_module
from app.main import app

# Importing Base from app.models (rather than app.models.base) also registers
# every table on Base.metadata, which create_all below depends on.
from app.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

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
async def session() -> AsyncIterator[AsyncSession]:
    """An AsyncSession on a fresh in-memory SQLite DB, isolated per test.

    StaticPool keeps every checkout on one connection, so the ``:memory:``
    database survives across sessions within a single test instead of being
    dropped when a pooled connection is recycled.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionFactory() as session:
            yield session
    finally:
        await engine.dispose()


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
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    """A client whose requests each get a fresh session from the real get_session.

    The `client` fixture above cannot test the request transaction boundary: it
    overrides get_session to hand every request one long-lived session, so a
    flush in request A is visible to request B whether or not anything ever
    commits. This fixture deliberately leaves get_session alone and gives each
    request its own session, so data only crosses a request boundary if
    get_session actually commits.

    One StaticPool engine backs every session, so all sessions see the same
    ``:memory:`` database and committed rows outlive the session that wrote them.
    """
    test_engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # get_session resolves SessionFactory as a module global on each call,
        # so patching the attribute is enough — and each call builds its OWN
        # session, which is the whole point of this fixture.
        monkeypatch.setattr(engine_module, "engine", test_engine)
        monkeypatch.setattr(
            engine_module,
            "SessionFactory",
            async_sessionmaker(test_engine, expire_on_commit=False),
        )

        # No dependency_overrides entry: the real, committing get_session is the
        # thing under test. Assert it, so a leaked override from another fixture
        # cannot silently turn this back into the shared-session setup.
        assert engine_module.get_session not in app.dependency_overrides

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await test_engine.dispose()


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
