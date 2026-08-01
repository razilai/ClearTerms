"""Shared pytest fixtures.

Run from backend/ so the editable install resolves `app`:

    uv run --project backend pytest

The DB layer is not implemented yet; tests/fakes.py patches app.db.repos with
in-memory fakes and the session dependency yields None (unused by fakes).
When the real DB lands, swap these for an in-memory SQLite engine + session
override; the endpoint tests themselves stay valid.
"""

from collections.abc import AsyncIterator

import httpx
import pytest

from tests.fakes import FakeStore, install


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    s = FakeStore()
    install(monkeypatch, s)
    return s


@pytest.fixture
async def client(store: FakeStore) -> AsyncIterator[httpx.AsyncClient]:
    from app.db.engine import get_session
    from app.main import app

    async def _null_session() -> AsyncIterator[None]:
        yield None

    app.dependency_overrides[get_session] = _null_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def signup_headers(
    client: httpx.AsyncClient, email: str, password: str = "hunter2!"
) -> dict[str, str]:
    resp = await client.post(
        "/auth/signup", json={"email": email, "password": password}
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    return await signup_headers(client, "alice@example.com")
