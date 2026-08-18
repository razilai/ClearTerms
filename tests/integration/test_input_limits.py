"""Integration tests: input length caps across endpoints."""


import httpx
import pytest

from app.core.config import settings
from app.services import auth
from tests.conftest import signup_headers
from tests.integration.factories import _create_post

# --- input length caps ---


async def test_signup_overlong_password(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/auth/signup",
        json={
            "email": "new@example.com",
            "password": "x" * (settings.max_password_chars + 1),
        },
    )
    assert resp.status_code == 422


async def test_signup_overlong_email(client: httpx.AsyncClient) -> None:
    local = "x" * settings.max_email_chars
    resp = await client.post(
        "/auth/signup", json={"email": f"{local}@example.com", "password": "s3cretpass"}
    )
    assert resp.status_code == 422


async def test_login_overlong_password_is_rejected_without_hashing(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap exists to keep argon2 off unbounded input, so assert the hasher
    is never reached — a 401 alone would also pass if the check ran after it."""
    await signup_headers(client, "bob@example.com", "s3cretpass")

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("password hasher must not run on an over-long input")

    monkeypatch.setattr(auth._pwd, "verify", _boom)
    monkeypatch.setattr(auth._pwd, "verify_and_update", _boom)

    resp = await client.post(
        "/auth/login",
        data={
            "username": "bob@example.com",
            "password": "x" * (settings.max_password_chars + 1),
        },
    )
    assert resp.status_code == 401


async def test_login_overlong_email_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        data={
            "username": "x" * (settings.max_email_chars + 1) + "@example.com",
            "password": "s3cretpass",
        },
    )
    assert resp.status_code == 401


async def test_login_accepts_a_password_at_the_cap(client: httpx.AsyncClient) -> None:
    """Boundary is inclusive — the longest allowed password must still log in."""
    password = "x" * settings.max_password_chars
    await signup_headers(client, "long@example.com", password)
    resp = await client.post(
        "/auth/login", data={"username": "long@example.com", "password": password}
    )
    assert resp.status_code == 200


async def test_post_overlong_title_rejected(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post(
        "/forum/posts",
        json={"title": "x" * (settings.max_post_title_chars + 1), "body": "ok"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_post_overlong_body_rejected(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post(
        "/forum/posts",
        json={"title": "ok", "body": "x" * (settings.max_post_body_chars + 1)},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_post_body_at_the_cap_accepted(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post(
        "/forum/posts",
        json={"title": "ok", "body": "x" * settings.max_post_body_chars},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text


async def test_comment_overlong_body_rejected(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    resp = await client.post(
        f"/forum/posts/{post_id}/comments",
        json={"body": "x" * (settings.max_comment_body_chars + 1)},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_comment_edit_cannot_exceed_the_create_cap(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """Otherwise editing is a way around the cap enforced on create."""
    post_id = await _create_post(client, auth_headers)
    comment_id = (
        await client.post(
            f"/forum/posts/{post_id}/comments",
            json={"body": "short"},
            headers=auth_headers,
        )
    ).json()["id"]
    resp = await client.patch(
        f"/forum/comments/{comment_id}",
        json={"body": "x" * (settings.max_comment_body_chars + 1)},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_analyze_overlong_url_rejected(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post(
        "/analyze",
        json={"text": "short", "url": "https://ex.test/" + "x" * settings.max_url_chars},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_missing_auth_header(client: httpx.AsyncClient) -> None:
    resp = await client.get("/forum/posts")
    assert resp.status_code == 401


async def test_garbage_bearer_token(client: httpx.AsyncClient) -> None:
    resp = await client.get(
        "/forum/posts", headers={"Authorization": "Bearer garbage"}
    )
    assert resp.status_code == 401
