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

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import engine as engine_module
from app.main import app

# Importing Base from app.models (rather than app.models.base) also registers
# every table on Base.metadata, which create_all below depends on.
from app.models import Base


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
