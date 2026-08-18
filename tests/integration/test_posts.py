"""Integration tests: forum posts."""


import httpx

from tests.integration.factories import POST_BODY, _create_post

# --- posts ---


async def test_create_post(client: httpx.AsyncClient, auth_headers: dict) -> None:
    resp = await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["author_email"] == "alice@example.com"
    assert body["title"] == POST_BODY["title"]
    assert body["like_count"] == 0


async def test_list_posts(client: httpx.AsyncClient, auth_headers: dict) -> None:
    await _create_post(client, auth_headers)
    resp = await client.get("/forum/posts", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["next_cursor"] is None
    posts = body["items"]
    assert len(posts) == 1
    assert posts[0]["author_email"] == "alice@example.com"


async def test_list_posts_paginates_by_cursor(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    for _ in range(3):
        await _create_post(client, auth_headers)

    first = (
        await client.get("/forum/posts?limit=2", headers=auth_headers)
    ).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None

    second = (
        await client.get(
            f"/forum/posts?limit=2&cursor={first['next_cursor']}",
            headers=auth_headers,
        )
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None

    ids = [p["id"] for p in first["items"]] + [p["id"] for p in second["items"]]
    # No overlap between pages, and every post shows up exactly once.
    assert len(set(ids)) == 3
    # Newest-first ordering holds across the page boundary.
    assert ids == sorted(ids, reverse=True)


async def test_list_posts_rejects_malformed_cursor(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.get("/forum/posts?cursor=not-a-cursor", headers=auth_headers)
    assert resp.status_code == 400


async def test_comments_paginate_by_cursor(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    for i in range(3):
        await client.post(
            f"/forum/posts/{post_id}/comments",
            json={"body": f"comment {i}"},
            headers=auth_headers,
        )

    first = (
        await client.get(
            f"/forum/posts/{post_id}/comments?limit=2", headers=auth_headers
        )
    ).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None

    second = (
        await client.get(
            f"/forum/posts/{post_id}/comments?limit=2&cursor={first['next_cursor']}",
            headers=auth_headers,
        )
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None

    bodies = [c["body"] for c in first["items"] + second["items"]]
    # Oldest-first, contiguous across the page boundary.
    assert bodies == ["comment 0", "comment 1", "comment 2"]


async def test_post_detail_with_comments(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    await client.post(
        f"/forum/posts/{post_id}/comments",
        json={"body": "Same in their privacy policy."},
        headers=auth_headers,
    )
    resp = await client.get(f"/forum/posts/{post_id}", headers=auth_headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert len(detail["comments"]) == 1
    assert detail["comments"][0]["author_email"] == "alice@example.com"
    assert detail["comments"][0]["edited_at"] is None


async def test_get_missing_post(client: httpx.AsyncClient, auth_headers: dict) -> None:
    resp = await client.get("/forum/posts/9999", headers=auth_headers)
    assert resp.status_code == 404


async def test_delete_own_post(client: httpx.AsyncClient, auth_headers: dict) -> None:
    post_id = await _create_post(client, auth_headers)
    resp = await client.delete(f"/forum/posts/{post_id}", headers=auth_headers)
    assert resp.status_code == 204
    resp = await client.get(f"/forum/posts/{post_id}", headers=auth_headers)
    assert resp.status_code == 404
