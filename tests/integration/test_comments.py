"""Integration tests: comments."""


import httpx

from tests.conftest import signup_headers
from tests.integration.factories import _post_and_comment

# --- comments ---


async def test_comment_on_missing_post(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post(
        "/forum/posts/9999/comments", json={"body": "hi"}, headers=auth_headers
    )
    assert resp.status_code == 404


async def test_edit_own_comment(client: httpx.AsyncClient, auth_headers: dict) -> None:
    _, comment_id = await _post_and_comment(client, auth_headers)
    resp = await client.patch(
        f"/forum/comments/{comment_id}", json={"body": "edited"}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["body"] == "edited"
    assert body["edited_at"] is not None


async def test_edit_other_users_comment(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    _, comment_id = await _post_and_comment(client, auth_headers)
    mallory = await signup_headers(client, "mallory@example.com")
    resp = await client.patch(
        f"/forum/comments/{comment_id}", json={"body": "hijack"}, headers=mallory
    )
    assert resp.status_code == 403


async def test_edit_missing_comment(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.patch(
        "/forum/comments/9999", json={"body": "x"}, headers=auth_headers
    )
    assert resp.status_code == 404


async def test_delete_own_comment(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    _, comment_id = await _post_and_comment(client, auth_headers)
    resp = await client.delete(f"/forum/comments/{comment_id}", headers=auth_headers)
    assert resp.status_code == 204


async def test_delete_other_users_comment(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    _, comment_id = await _post_and_comment(client, auth_headers)
    mallory = await signup_headers(client, "mallory@example.com")
    resp = await client.delete(f"/forum/comments/{comment_id}", headers=mallory)
    assert resp.status_code == 403
