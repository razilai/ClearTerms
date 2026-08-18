"""Integration tests: auth endpoints."""


import httpx

from app.services import auth
from tests.conftest import signup_headers

# --- auth ---


async def test_signup_returns_token(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/auth/signup", json={"email": "new@example.com", "password": "s3cretpass"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_signup_short_password(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/auth/signup", json={"email": "new@example.com", "password": "short"}
    )
    assert resp.status_code == 422


async def test_signup_email_lowercased(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/auth/signup", json={"email": "Bob@Example.COM", "password": "s3cretpass"}
    )
    assert resp.status_code == 201
    resp = await client.post(
        "/auth/login", data={"username": "bob@example.com", "password": "s3cretpass"}
    )
    assert resp.status_code == 200


async def test_signup_duplicate_email(client: httpx.AsyncClient) -> None:
    await signup_headers(client, "dup@example.com")
    resp = await client.post(
        "/auth/signup", json={"email": "dup@example.com", "password": "otherpass"}
    )
    assert resp.status_code == 409


async def test_login_ok(client: httpx.AsyncClient) -> None:
    await signup_headers(client, "bob@example.com", "s3cretpass")
    resp = await client.post(
        "/auth/login", data={"username": "bob@example.com", "password": "s3cretpass"}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_login_wrong_password(client: httpx.AsyncClient) -> None:
    await signup_headers(client, "bob@example.com", "s3cretpass")
    resp = await client.post(
        "/auth/login", data={"username": "bob@example.com", "password": "nope"}
    )
    assert resp.status_code == 401


async def test_login_unknown_email(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/auth/login", data={"username": "ghost@example.com", "password": "pw"}
    )
    assert resp.status_code == 401


async def test_valid_token_for_nonexistent_user_is_rejected(
    client: httpx.AsyncClient,
) -> None:
    """A correctly signed token whose subject no longer exists (deleted account,
    or an id that never existed) must 401 — signature validity alone is not
    authorisation; CurrentUserDep still has to find the row."""
    token = auth.create_access_token(999_999)
    resp = await client.get(
        "/forum/posts", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401
