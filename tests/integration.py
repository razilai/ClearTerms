"""Integration tests: auth + forum endpoints against the app with faked repos."""

import httpx

from tests.conftest import signup_headers

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
    posts = resp.json()
    assert len(posts) == 1
    assert posts[0]["author_email"] == "alice@example.com"


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
# real repos and the dummy classifier (app.agent.classifier.analyze returns a
# score of 1 for every category, so no Ollama is needed).

ANALYZE_BODY = {"text": "You agree to binding arbitration.", "url": "https://ex.test/tos"}


async def test_analyze_returns_verdict_and_id(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post("/analyze", json=ANALYZE_BODY, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Dummy scores are all 1 (standard), so with default weights the verdict is up.
    assert body["verdict"] == "up"
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
    # One CategoryScore per clause category from the dummy classifier.
    assert len(body["scores"]) == 6
    assert {s["score"] for s in body["scores"]} == {1}


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
    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["url"] == "https://ex.test/tos"
    assert entries[0]["verdict"] == "up"


async def test_history_empty_for_new_user(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.get("/history", headers=auth_headers)
    assert resp.json() == {"entries": []}


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
