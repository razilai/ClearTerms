"""Integration tests: auth + forum endpoints against a real in-memory SQLite DB."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import forum as forum_repo
from tests.conftest import signup_headers

# Minimal valid PNG (1x1 px, smallest valid file)
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)

POST_BODY = {"title": "Sneaky arbitration clause", "body": "Section 12 forces arbitration."}


async def _create_post(client: httpx.AsyncClient, headers: dict) -> int:
    resp = await client.post("/forum/posts", json=POST_BODY, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


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


async def test_missing_auth_header(client: httpx.AsyncClient) -> None:
    resp = await client.get("/forum/posts")
    assert resp.status_code == 401


async def test_garbage_bearer_token(client: httpx.AsyncClient) -> None:
    resp = await client.get(
        "/forum/posts", headers={"Authorization": "Bearer garbage"}
    )
    assert resp.status_code == 401


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


async def test_delete_post_cascades_children(
    client: httpx.AsyncClient, auth_headers: dict, session: AsyncSession
) -> None:
    # Deleting a post is one DELETE; the comments.post_id / likes.post_id
    # ondelete=CASCADE drops the children in the db (no app-level sweep).
    post_id = await _create_post(client, auth_headers)
    await client.post(
        f"/forum/posts/{post_id}/comments",
        json={"body": "a comment"},
        headers=auth_headers,
    )
    await client.put(f"/forum/posts/{post_id}/like", headers=auth_headers)

    resp = await client.delete(f"/forum/posts/{post_id}", headers=auth_headers)
    assert resp.status_code == 204

    # The shared session sees the cascade even before commit.
    assert await forum_repo.list_comments(session, post_id, limit=50) == []
    assert await forum_repo.count_likes(session, post_id) == 0


async def test_delete_other_users_post(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    mallory = await signup_headers(client, "mallory@example.com")
    resp = await client.delete(f"/forum/posts/{post_id}", headers=mallory)
    assert resp.status_code == 403


# --- comments ---


async def _post_and_comment(
    client: httpx.AsyncClient, headers: dict
) -> tuple[int, int]:
    post_id = await _create_post(client, headers)
    comment_id = (
        await client.post(
            f"/forum/posts/{post_id}/comments",
            json={"body": "original"},
            headers=headers,
        )
    ).json()["id"]
    return post_id, comment_id


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


# --- likes ---


async def test_toggle_like(client: httpx.AsyncClient, auth_headers: dict) -> None:
    post_id = await _create_post(client, auth_headers)
    resp = await client.put(f"/forum/posts/{post_id}/like", headers=auth_headers)
    assert resp.json() == {"like_count": 1, "liked": True}
    resp = await client.put(f"/forum/posts/{post_id}/like", headers=auth_headers)
    assert resp.json() == {"like_count": 0, "liked": False}


async def test_like_missing_post(client: httpx.AsyncClient, auth_headers: dict) -> None:
    resp = await client.put("/forum/posts/9999/like", headers=auth_headers)
    assert resp.status_code == 404


# --- analysis + history + preferences ---
#
# Run the whole pipeline (analyze -> cache -> verdict -> history) against the
# real repos and a real agent. Per conftest's `light_agent` fixture the model is
# a tiny one, so a live Ollama IS required (CI installs it and pulls the model);
# scores are therefore nondeterministic, and the assertions below check shape,
# not fixed values.

ANALYZE_BODY = {"text": "You agree to binding arbitration.", "url": "https://ex.test/tos"}


async def test_analyze_returns_verdict_and_id(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post("/analyze", json=ANALYZE_BODY, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Live agent scores are nondeterministic; assert shape, not a fixed verdict.
    assert body["verdict"] in {"up", "down"}
    assert isinstance(body["analysis_id"], int)


async def test_analyze_is_cached_across_calls(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    first = await client.post("/analyze", json=ANALYZE_BODY, headers=auth_headers)
    second = await client.post("/analyze", json=ANALYZE_BODY, headers=auth_headers)
    # Same normalized text -> same document -> same analysis_id.
    assert first.json()["analysis_id"] == second.json()["analysis_id"]


async def test_analyze_too_large(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    big = {"text": "x" * 1_000_001, "url": None}
    resp = await client.post("/analyze", json=big, headers=auth_headers)
    assert resp.status_code == 413


async def test_analysis_detail(client: httpx.AsyncClient, auth_headers: dict) -> None:
    analysis_id = (
        await client.post("/analyze", json=ANALYZE_BODY, headers=auth_headers)
    ).json()["analysis_id"]

    resp = await client.get(f"/analyses/{analysis_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == analysis_id
    assert body["url"] == "https://ex.test/tos"
    # One CategoryScore per clause category.
    assert len(body["scores"]) == 6
    # Live agent scores are nondeterministic; each must be on the 0-2 scale.
    assert {s["score"] for s in body["scores"]} <= {0, 1, 2}


async def test_analysis_detail_missing(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.get("/analyses/9999", headers=auth_headers)
    assert resp.status_code == 404


async def test_history_lists_analyzed_documents(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    await client.post("/analyze", json=ANALYZE_BODY, headers=auth_headers)

    resp = await client.get("/history", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["next_cursor"] is None
    entries = body["items"]
    assert len(entries) == 1
    assert entries[0]["url"] == "https://ex.test/tos"
    assert entries[0]["verdict"] in {"up", "down"}


async def test_history_empty_for_new_user(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.get("/history", headers=auth_headers)
    assert resp.json() == {"items": [], "next_cursor": None}


async def test_preferences_round_trip(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    assert (await client.get("/preferences", headers=auth_headers)).json() == {
        "items": []
    }

    items = [{"category": "arbitration", "weight": 0.0}]
    put = await client.put(
        "/preferences", json={"items": items}, headers=auth_headers
    )
    assert put.status_code == 200
    assert put.json() == {"items": items}
    assert (await client.get("/preferences", headers=auth_headers)).json() == {
        "items": items
    }


async def test_preferences_duplicate_category_rejected(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    items = [
        {"category": "arbitration", "weight": 0.5},
        {"category": "arbitration", "weight": 1.0},
    ]
    resp = await client.put(
        "/preferences", json={"items": items}, headers=auth_headers
    )
    assert resp.status_code == 400


# --- request transaction boundary ---
#
# Uses `committing_client`, not `client`: see that fixture's docstring for why
# the shared-session client cannot catch a missing commit.


async def test_writes_persist_across_requests(
    committing_client: httpx.AsyncClient,
) -> None:
    """Signup in one request must be readable by a later, separate request.

    Both requests run on their own session, so the user row is only visible to
    the second one because get_session committed the first. Drop the commit and
    the signup is rolled back at session close, and the login 401s.
    """
    signup = await committing_client.post(
        "/auth/signup", json={"email": "persist@example.com", "password": "s3cretpass"}
    )
    assert signup.status_code == 201, signup.text

    login = await committing_client.post(
        "/auth/login",
        data={"username": "persist@example.com", "password": "s3cretpass"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["access_token"]


# --- attachments ---
#
# Storage is faked (in-memory dict) and the processor is a synchronous stub that
# immediately marks attachments ready. No MinIO, no ffmpeg, no Pillow needed in
# the default test suite. Real processing is exercised behind the `slow` marker.


async def _upload_png(
    client: httpx.AsyncClient, headers: dict
) -> tuple[int, dict]:
    """Upload the tiny PNG and return (attachment_id, response_body)."""
    files = {"file": ("test.png", _TINY_PNG, "image/png")}
    resp = await client.post("/forum/attachments", files=files, headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["id"], body


async def test_upload_attachment_returns_pending(
    client: httpx.AsyncClient,
    auth_headers: dict,
    fake_storage: dict,
) -> None:
    # Background task runs synchronously in tests via the stub processor.
    # But the upload handler fires it AFTER returning, so at response time
    # the status is "pending". The poll endpoint then shows "ready".
    attachment_id, body = await _upload_png(client, auth_headers)
    assert body["media_type"] == "image"
    assert body["status"] == "pending"
    assert body["id"] == attachment_id


async def test_poll_attachment_becomes_ready(
    committing_client: httpx.AsyncClient,
    fake_storage: dict,
) -> None:
    """Background stub commits, so committing_client sees the update."""
    headers = await signup_headers(committing_client, "poll@example.com")
    files = {"file": ("img.png", _TINY_PNG, "image/png")}
    resp = await committing_client.post(
        "/forum/attachments", files=files, headers=headers
    )
    assert resp.status_code == 201, resp.text
    attachment_id = resp.json()["id"]

    poll = await committing_client.get(
        f"/forum/attachments/{attachment_id}", headers=headers
    )
    assert poll.status_code == 200
    body = poll.json()
    assert body["status"] == "ready"
    assert body["display_url"] is not None
    assert body["thumbnail_url"] is not None
    assert body["width"] == 640
    assert body["height"] == 480


async def test_post_with_attachment(
    committing_client: httpx.AsyncClient,
    fake_storage: dict,
) -> None:
    headers = await signup_headers(committing_client, "attach@example.com")
    files = {"file": ("img.png", _TINY_PNG, "image/png")}
    att_id = (
        await committing_client.post(
            "/forum/attachments", files=files, headers=headers
        )
    ).json()["id"]

    post_resp = await committing_client.post(
        "/forum/posts",
        json={**POST_BODY, "attachment_ids": [att_id]},
        headers=headers,
    )
    assert post_resp.status_code == 201, post_resp.text
    post = post_resp.json()
    assert len(post["attachments"]) == 1
    assert post["attachments"][0]["id"] == att_id

    # Attachment now linked — claiming again should 404
    post2_resp = await committing_client.post(
        "/forum/posts",
        json={**POST_BODY, "attachment_ids": [att_id]},
        headers=headers,
    )
    assert post2_resp.status_code == 404


async def test_comment_with_attachment(
    committing_client: httpx.AsyncClient,
    fake_storage: dict,
) -> None:
    headers = await signup_headers(committing_client, "comment_att@example.com")
    files = {"file": ("img.png", _TINY_PNG, "image/png")}
    att_id = (
        await committing_client.post(
            "/forum/attachments", files=files, headers=headers
        )
    ).json()["id"]

    post_id = (
        await committing_client.post(
            "/forum/posts", json=POST_BODY, headers=headers
        )
    ).json()["id"]

    comment_resp = await committing_client.post(
        f"/forum/posts/{post_id}/comments",
        json={"body": "with attachment", "attachment_ids": [att_id]},
        headers=headers,
    )
    assert comment_resp.status_code == 201, comment_resp.text
    assert len(comment_resp.json()["attachments"]) == 1


async def test_cannot_claim_other_users_attachment(
    committing_client: httpx.AsyncClient,
    fake_storage: dict,
) -> None:
    alice = await signup_headers(committing_client, "alice2@example.com")
    mallory = await signup_headers(committing_client, "mallory2@example.com")

    files = {"file": ("img.png", _TINY_PNG, "image/png")}
    att_id = (
        await committing_client.post(
            "/forum/attachments", files=files, headers=alice
        )
    ).json()["id"]

    resp = await committing_client.post(
        "/forum/posts",
        json={**POST_BODY, "attachment_ids": [att_id]},
        headers=mallory,
    )
    assert resp.status_code == 404


async def test_upload_unsupported_type(
    client: httpx.AsyncClient,
    auth_headers: dict,
    fake_storage: dict,
) -> None:
    files = {"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")}
    resp = await client.post("/forum/attachments", files=files, headers=auth_headers)
    assert resp.status_code == 415


async def test_upload_file_too_large(
    client: httpx.AsyncClient,
    auth_headers: dict,
    fake_storage: dict,
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    import pytest
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_image_bytes", 10)
    files = {"file": ("img.png", _TINY_PNG, "image/png")}
    resp = await client.post("/forum/attachments", files=files, headers=auth_headers)
    assert resp.status_code == 413


async def test_delete_post_removes_attachment_objects(
    committing_client: httpx.AsyncClient,
    fake_storage: dict,
) -> None:
    headers = await signup_headers(committing_client, "del_att@example.com")
    files = {"file": ("img.png", _TINY_PNG, "image/png")}
    att_id = (
        await committing_client.post(
            "/forum/attachments", files=files, headers=headers
        )
    ).json()["id"]

    post_id = (
        await committing_client.post(
            "/forum/posts",
            json={**POST_BODY, "attachment_ids": [att_id]},
            headers=headers,
        )
    ).json()["id"]

    # Storage has keys before delete
    assert any(f"attachments/{att_id}" in k for k in fake_storage)

    del_resp = await committing_client.delete(
        f"/forum/posts/{post_id}", headers=headers
    )
    assert del_resp.status_code == 204

    # Object keys removed from fake store
    assert not any(f"attachments/{att_id}" in k for k in fake_storage)
