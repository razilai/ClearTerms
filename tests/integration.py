"""Integration tests: auth, forum, and analysis endpoints against a real in-memory SQLite DB."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.repos import forum as forum_repo
from app.models import CommentVote, PostVote, User
from app.services import auth
from app.services import rate_limit as rate_limit_service
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


async def _start_conversation(
    client: httpx.AsyncClient, headers: dict, recipient: str = "bob@example.com"
) -> int:
    """Open the caller's thread with ``recipient``, signing them up if needed.

    409 on the signup just means an earlier call in this test already created
    them — the recipient has to exist because the API names people by email.
    """
    signup = await client.post(
        "/auth/signup", json={"email": recipient, "password": "hunter2!"}
    )
    assert signup.status_code in (201, 409), signup.text
    resp = await client.post(
        "/messages/conversations", json={"recipient_email": recipient}, headers=headers
    )
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


async def test_message_overlong_body_rejected(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    conversation_id = await _start_conversation(client, auth_headers)
    resp = await client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "x" * (settings.max_message_body_chars + 1)},
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


# --- anonymous posts ---

_ANON_BODY = {**POST_BODY, "is_anonymous": True}


async def _create_anon_post(client: httpx.AsyncClient, headers: dict) -> int:
    resp = await client.post("/forum/posts", json=_ANON_BODY, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_create_post_defaults_to_non_anonymous(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    assert resp.json()["is_anonymous"] is False


async def test_create_anonymous_post_returns_own_email(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post("/forum/posts", json=_ANON_BODY, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["is_anonymous"] is True
    assert body["author_email"] == "alice@example.com"


async def test_anonymous_post_hides_email_from_others(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_anon_post(client, auth_headers)
    other = await signup_headers(client, "bob@example.com")

    listed = (await client.get("/forum/posts", headers=other)).json()["items"][0]
    assert listed["author_email"] is None
    assert listed["is_anonymous"] is True

    detail = (await client.get(f"/forum/posts/{post_id}", headers=other)).json()
    assert detail["author_email"] is None
    assert detail["is_anonymous"] is True


async def test_anonymous_post_shows_email_to_author(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_anon_post(client, auth_headers)

    listed = (await client.get("/forum/posts", headers=auth_headers)).json()["items"][0]
    assert listed["author_email"] == "alice@example.com"

    detail = (await client.get(f"/forum/posts/{post_id}", headers=auth_headers)).json()
    assert detail["author_email"] == "alice@example.com"


async def test_anonymous_post_delete_stays_owner_only(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_anon_post(client, auth_headers)
    other = await signup_headers(client, "bob@example.com")

    resp = await client.delete(f"/forum/posts/{post_id}", headers=other)
    assert resp.status_code == 403
    resp = await client.delete(f"/forum/posts/{post_id}", headers=auth_headers)
    assert resp.status_code == 204


async def _comment(client: httpx.AsyncClient, headers: dict, post_id: int, body: str) -> int:
    resp = await client.post(
        f"/forum/posts/{post_id}/comments", json={"body": body}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_anonymous_post_masks_author_comments_from_others(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """The post author's own comments inherit the post's anonymity — otherwise
    replying by name under your own anonymous post deanonymizes it."""
    post_id = await _create_anon_post(client, auth_headers)
    await _comment(client, auth_headers, post_id, "author reply")
    other = await signup_headers(client, "bob@example.com")
    await _comment(client, other, post_id, "bob reply")

    comments = (await client.get(f"/forum/posts/{post_id}", headers=other)).json()[
        "comments"
    ]
    by_body = {c["body"]: c for c in comments}
    assert by_body["author reply"]["author_email"] is None
    assert by_body["author reply"]["is_anonymous"] is True
    # A different commenter is not anonymised by the post's flag.
    assert by_body["bob reply"]["author_email"] == "bob@example.com"
    assert by_body["bob reply"]["is_anonymous"] is False


async def test_anonymous_post_author_sees_own_comment_email(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_anon_post(client, auth_headers)
    await _comment(client, auth_headers, post_id, "author reply")

    comment = (await client.get(f"/forum/posts/{post_id}", headers=auth_headers)).json()[
        "comments"
    ][0]
    assert comment["author_email"] == "alice@example.com"
    assert comment["is_anonymous"] is True


async def test_comment_on_public_post_is_not_anonymous(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id, _ = await _post_and_comment(client, auth_headers)
    other = await signup_headers(client, "bob@example.com")

    comment = (await client.get(f"/forum/posts/{post_id}", headers=other)).json()[
        "comments"
    ][0]
    assert comment["author_email"] == "alice@example.com"
    assert comment["is_anonymous"] is False


async def test_edit_comment_keeps_anonymity_flag(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_anon_post(client, auth_headers)
    comment_id = await _comment(client, auth_headers, post_id, "author reply")

    resp = await client.patch(
        f"/forum/comments/{comment_id}", json={"body": "edited"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_anonymous"] is True


async def test_new_comment_on_anonymous_post_is_flagged(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_anon_post(client, auth_headers)
    resp = await client.post(
        f"/forum/posts/{post_id}/comments", json={"body": "hi"}, headers=auth_headers
    )
    assert resp.json()["is_anonymous"] is True


async def test_delete_post_cascades_children(
    client: httpx.AsyncClient, auth_headers: dict, session: AsyncSession
) -> None:
    # Deleting a post is one DELETE; the comments.post_id / post_votes.target_id
    # ondelete=CASCADE drops the children in the db (no app-level sweep). Comment
    # votes go two hops: post -> comment -> comment_votes.target_id.
    post_id, comment_id = await _post_and_comment(client, auth_headers)
    await client.put(
        f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=auth_headers
    )
    await client.put(
        f"/forum/comments/{comment_id}/vote", json={"value": 1}, headers=auth_headers
    )

    resp = await client.delete(f"/forum/posts/{post_id}", headers=auth_headers)
    assert resp.status_code == 204

    # The shared session sees the cascade even before commit.
    assert await forum_repo.list_comments(session, post_id, limit=50) == []
    assert await forum_repo.count_votes(session, PostVote, [post_id]) == {}
    assert await forum_repo.count_votes(session, CommentVote, [comment_id]) == {}


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


# --- votes ---

async def test_vote_post_toggles_and_switches(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)

    resp = await client.put(
        f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=auth_headers
    )
    assert resp.json() == {"like_count": 1, "dislike_count": 0, "my_vote": 1}

    # Same value again clears the vote.
    resp = await client.put(
        f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=auth_headers
    )
    assert resp.json() == {"like_count": 0, "dislike_count": 0, "my_vote": 0}

    # A like followed by a dislike switches sides — it does not stack.
    await client.put(
        f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=auth_headers
    )
    resp = await client.put(
        f"/forum/posts/{post_id}/vote", json={"value": -1}, headers=auth_headers
    )
    assert resp.json() == {"like_count": 0, "dislike_count": 1, "my_vote": -1}


async def test_vote_comment(client: httpx.AsyncClient, auth_headers: dict) -> None:
    _, comment_id = await _post_and_comment(client, auth_headers)
    resp = await client.put(
        f"/forum/comments/{comment_id}/vote", json={"value": -1}, headers=auth_headers
    )
    assert resp.json() == {"like_count": 0, "dislike_count": 1, "my_vote": -1}


async def test_vote_missing_target(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.put(
        "/forum/posts/9999/vote", json={"value": 1}, headers=auth_headers
    )
    assert resp.status_code == 404
    resp = await client.put(
        "/forum/comments/9999/vote", json={"value": 1}, headers=auth_headers
    )
    assert resp.status_code == 404


async def test_vote_rejects_bad_value(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    resp = await client.put(
        f"/forum/posts/{post_id}/vote", json={"value": 2}, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_post_read_paths_report_my_vote(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    await client.put(
        f"/forum/posts/{post_id}/vote", json={"value": -1}, headers=auth_headers
    )

    detail = (await client.get(f"/forum/posts/{post_id}", headers=auth_headers)).json()
    assert (detail["like_count"], detail["dislike_count"], detail["my_vote"]) == (0, 1, -1)

    listed = (await client.get("/forum/posts", headers=auth_headers)).json()["items"][0]
    assert (listed["like_count"], listed["dislike_count"], listed["my_vote"]) == (0, 1, -1)


async def test_my_vote_is_per_user(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """Counts are global; my_vote is the requester's own and nobody else's."""
    post_id = await _create_post(client, auth_headers)
    await client.put(
        f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=auth_headers
    )

    bob = await signup_headers(client, "bob@example.com")
    detail = (await client.get(f"/forum/posts/{post_id}", headers=bob)).json()
    assert detail["like_count"] == 1
    assert detail["my_vote"] == 0


async def test_comment_read_paths_report_my_vote(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id, comment_id = await _post_and_comment(client, auth_headers)
    await client.put(
        f"/forum/comments/{comment_id}/vote", json={"value": 1}, headers=auth_headers
    )

    # Embedded first page inside the post detail.
    detail = (await client.get(f"/forum/posts/{post_id}", headers=auth_headers)).json()
    assert detail["comments"][0]["my_vote"] == 1
    assert detail["comments"][0]["like_count"] == 1

    # And the standalone cursor-paged route.
    page = (
        await client.get(f"/forum/posts/{post_id}/comments", headers=auth_headers)
    ).json()
    assert page["items"][0]["my_vote"] == 1


async def test_edit_comment_keeps_vote_state(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    _, comment_id = await _post_and_comment(client, auth_headers)
    await client.put(
        f"/forum/comments/{comment_id}/vote", json={"value": 1}, headers=auth_headers
    )
    edited = (
        await client.patch(
            f"/forum/comments/{comment_id}",
            json={"body": "edited"},
            headers=auth_headers,
        )
    ).json()
    assert edited["like_count"] == 1
    assert edited["my_vote"] == 1


# --- personal area: my posts + my vote totals ---


async def test_my_posts_lists_only_own_posts(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    mine = await _create_post(client, auth_headers)
    bob = await signup_headers(client, "bob@example.com")
    await _create_post(client, bob)

    body = (await client.get("/forum/posts/mine", headers=auth_headers)).json()
    assert [p["id"] for p in body["items"]] == [mine]


async def test_my_posts_paginate_by_cursor(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    for _ in range(3):
        await _create_post(client, auth_headers)

    first = (await client.get("/forum/posts/mine?limit=2", headers=auth_headers)).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None

    second = (
        await client.get(
            f"/forum/posts/mine?limit=2&cursor={first['next_cursor']}",
            headers=auth_headers,
        )
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None

    ids = [p["id"] for p in first["items"]] + [p["id"] for p in second["items"]]
    assert len(set(ids)) == 3
    assert ids == sorted(ids, reverse=True)


async def test_my_posts_carries_vote_state(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    await client.put(
        f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=auth_headers
    )
    post = (await client.get("/forum/posts/mine", headers=auth_headers)).json()[
        "items"
    ][0]
    assert post["like_count"] == 1
    assert post["my_vote"] == 1


async def test_my_vote_totals_sums_votes_across_my_posts(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    first = await _create_post(client, auth_headers)
    second = await _create_post(client, auth_headers)
    bob = await signup_headers(client, "bob@example.com")
    carol = await signup_headers(client, "carol@example.com")
    await client.put(f"/forum/posts/{first}/vote", json={"value": 1}, headers=bob)
    await client.put(f"/forum/posts/{first}/vote", json={"value": 1}, headers=carol)
    await client.put(f"/forum/posts/{second}/vote", json={"value": -1}, headers=bob)

    totals = (await client.get("/forum/me/vote-totals", headers=auth_headers)).json()
    assert totals == {"post_count": 2, "like_count": 2, "dislike_count": 1}


async def test_my_vote_totals_ignore_other_authors_posts(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    bobs_post = await _create_post(client, bob)
    await client.put(
        f"/forum/posts/{bobs_post}/vote", json={"value": 1}, headers=auth_headers
    )

    totals = (await client.get("/forum/me/vote-totals", headers=auth_headers)).json()
    assert totals == {"post_count": 0, "like_count": 0, "dislike_count": 0}


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

    items = [{"category": "arbitration", "enabled": False}]
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
        {"category": "arbitration", "enabled": False},
        {"category": "arbitration", "enabled": True},
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
# Storage is faked (in-memory dict) and the processor is an async stub that
# immediately marks attachments ready. No MinIO or ffmpeg needed in the default
# suite. `test_upload_runs_real_image_processing` opts out of the stub to drive
# the real Pillow pipeline (still against the in-memory store, so no MinIO).


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


async def test_message_with_attachment(
    committing_client: httpx.AsyncClient,
    fake_storage: dict,
) -> None:
    """Round trip: claimed on send, visible to the recipient, and in the inbox
    preview so an attachments-only message isn't a blank row."""
    alice = await signup_headers(committing_client, "alice-dm-att@example.com")
    bob = await signup_headers(committing_client, "bob-dm-att@example.com")
    conversation_id = (
        await committing_client.post(
            "/messages/conversations",
            json={"recipient_email": "bob-dm-att@example.com"},
            headers=alice,
        )
    ).json()["id"]

    files = {"file": ("img.png", _TINY_PNG, "image/png")}
    att_id = (
        await committing_client.post(
            "/forum/attachments", files=files, headers=alice
        )
    ).json()["id"]

    sent = await committing_client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "look at this", "attachment_ids": [att_id]},
        headers=alice,
    )
    assert sent.status_code == 201, sent.text
    assert [a["id"] for a in sent.json()["attachments"]] == [att_id]

    detail = await committing_client.get(
        f"/messages/conversations/{conversation_id}", headers=bob
    )
    assert [a["id"] for a in detail.json()["messages"][0]["attachments"]] == [att_id]

    inbox = await committing_client.get("/messages/conversations", headers=bob)
    preview = inbox.json()["items"][0]["last_message"]
    assert [a["id"] for a in preview["attachments"]] == [att_id]


async def test_message_cannot_claim_another_users_attachment(
    committing_client: httpx.AsyncClient,
    fake_storage: dict,
) -> None:
    """Mirrors the forum's rule: an id you did not upload is not yours to send,
    and one already claimed cannot be claimed twice."""
    alice = await signup_headers(committing_client, "alice-dm-steal@example.com")
    mallory = await signup_headers(committing_client, "mallory-dm@example.com")
    conversation_id = (
        await committing_client.post(
            "/messages/conversations",
            json={"recipient_email": "alice-dm-steal@example.com"},
            headers=mallory,
        )
    ).json()["id"]

    files = {"file": ("img.png", _TINY_PNG, "image/png")}
    alice_att = (
        await committing_client.post(
            "/forum/attachments", files=files, headers=alice
        )
    ).json()["id"]

    stealing = await committing_client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "not mine", "attachment_ids": [alice_att]},
        headers=mallory,
    )
    assert stealing.status_code == 404

    # Mallory's own attachment, claimed once, cannot be re-sent.
    own = (
        await committing_client.post(
            "/forum/attachments", files=files, headers=mallory
        )
    ).json()["id"]
    first = await committing_client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "mine", "attachment_ids": [own]},
        headers=mallory,
    )
    assert first.status_code == 201, first.text
    again = await committing_client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "again", "attachment_ids": [own]},
        headers=mallory,
    )
    assert again.status_code == 404


async def test_message_body_optional_only_with_an_attachment(
    committing_client: httpx.AsyncClient,
    fake_storage: dict,
) -> None:
    """Deliberate divergence from posts: a picture with no caption is a normal
    message, but a message with neither text nor attachment is not."""
    alice = await signup_headers(committing_client, "alice-dm-empty@example.com")
    await signup_headers(committing_client, "bob-dm-empty@example.com")
    conversation_id = (
        await committing_client.post(
            "/messages/conversations",
            json={"recipient_email": "bob-dm-empty@example.com"},
            headers=alice,
        )
    ).json()["id"]

    empty = await committing_client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "   "},
        headers=alice,
    )
    assert empty.status_code == 400

    files = {"file": ("img.png", _TINY_PNG, "image/png")}
    att_id = (
        await committing_client.post(
            "/forum/attachments", files=files, headers=alice
        )
    ).json()["id"]
    caption_less = await committing_client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "", "attachment_ids": [att_id]},
        headers=alice,
    )
    assert caption_less.status_code == 201, caption_less.text
    assert caption_less.json()["body"] == ""


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


async def test_upload_commits_before_scheduling_processing(
    session: AsyncSession,
    fake_storage: dict,
) -> None:
    """Regression: the attachment row must be committed *before* the background
    processor is scheduled.

    In production the processor opens its own session on a separate pooled
    connection, so an uncommitted row is invisible to it: it reads ``None`` and
    returns, leaving the attachment stuck ``pending`` forever (the frontend then
    shows an endless loading skeleton). FastAPI runs BackgroundTasks before the
    request session's own commit, so ``upload_attachment`` must commit itself.

    The shared-connection test harness can't reproduce the cross-connection
    invisibility, so this asserts the ordering directly: at the moment the task
    is scheduled the session must no longer be in a transaction (i.e. it has
    committed). ``in_transaction()`` is True after a flush, False after commit.
    """
    import io

    from starlette.datastructures import Headers, UploadFile

    from app.db.repos import users as users_repo
    from app.services import forum as forum_service

    user = await users_repo.create(session, "committer@example.com", "hash")

    in_transaction_at_schedule: list[bool] = []

    class _SpyBackgroundTasks:
        def add_task(self, func, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            in_transaction_at_schedule.append(session.in_transaction())

    upload = UploadFile(
        file=io.BytesIO(_TINY_PNG),
        filename="t.png",
        headers=Headers({"content-type": "image/png"}),
    )

    await forum_service.upload_attachment(session, user, upload, _SpyBackgroundTasks())

    assert in_transaction_at_schedule == [False], (
        "attachment must be committed before the processing task is scheduled, "
        "or the out-of-band worker reads None and it stays pending forever"
    )


async def test_upload_runs_real_image_processing(
    committing_client: httpx.AsyncClient,
    fake_storage: dict,
) -> None:
    """End-to-end with the real Pillow pipeline (not the stub): upload a PNG,
    let the actual processor run, and assert it lands ``ready`` with a valid
    WebP display object in storage. Guards the whole upload->process->serve path
    a user hits, without needing MinIO (storage is the in-memory fake).
    """
    import io

    from PIL import Image

    from app.services import media as media_service

    # Opt out of the autouse stub processor; use the real one for this test.
    # (_TINY_PNG is header-valid but not fully decodable — build a real image so
    # Pillow's decoder, resize, and WebP encode all actually run.)
    media_service.set_processor(None)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format="PNG")
    png = buf.getvalue()

    headers = await signup_headers(committing_client, "realproc@example.com")
    files = {"file": ("img.png", png, "image/png")}
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
    assert body["status"] == "ready", body
    assert body["display_url"] is not None
    assert body["thumbnail_url"] is not None
    assert body["width"] == 8 and body["height"] == 8

    # Real processing wrote genuine WebP bytes to the (fake) object store.
    display_key = f"attachments/{attachment_id}/display.webp"
    assert display_key in fake_storage
    blob = fake_storage[display_key]
    assert blob[:4] == b"RIFF" and blob[8:12] == b"WEBP", "expected a WebP display object"


# --- error mapping ---
#
# Each test builds a throwaway probe app rather than registering routes on the
# shared app.main.app singleton — routes added to the real app are never
# removed and would leak into every later test in the session.


async def _probe_app_response(exc: Exception) -> httpx.Response:
    """Raise `exc` from a route on a throwaway app wired with the real handlers."""
    from fastapi import FastAPI

    from app.api.errors import register_exception_handlers

    probe = FastAPI()
    register_exception_handlers(probe)

    @probe.get("/boom")
    async def boom() -> None:
        raise exc

    transport = httpx.ASGITransport(app=probe)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get("/boom")


async def test_queue_full_maps_to_503() -> None:
    from app.services.exceptions import QueueFullError

    resp = await _probe_app_response(QueueFullError())
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Analysis queue is full, try again shortly"
    assert resp.headers["Retry-After"] == "30"


async def test_queue_shutdown_maps_to_503() -> None:
    from app.services.exceptions import QueueShutdownError

    resp = await _probe_app_response(QueueShutdownError())
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Analysis is shutting down, try again shortly"
    assert resp.headers["Retry-After"] == "30"


async def test_queue_timeout_maps_to_504() -> None:
    from app.services.exceptions import QueueTimeoutError

    resp = await _probe_app_response(QueueTimeoutError())
    assert resp.status_code == 504
    assert (
        resp.json()["detail"]
        == "Analysis is taking longer than expected, try again shortly"
    )


# --- analysis pipeline through a live queue ---------------------------------


async def test_analyze_runs_through_a_live_queue(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # The `client` fixture starts the queue itself (bound to the same
    # in-memory database the client's requests use); starting it again here
    # against a different, file-backed factory would point the worker at a
    # database the caller can't see its writes in.
    resp = await client.post(
        "/analyze",
        json={"text": "You waive all rights. We may share your data.", "url": None},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] in {"up", "down"}
    assert isinstance(body["analysis_id"], int)


async def test_vote_repo_counts_and_toggles(session: AsyncSession) -> None:
    """set_vote is an upsert; count_votes splits likes from dislikes."""
    from app.schemas.forum import PostCreate

    user = User(email="votes@example.com", password_hash="x")
    session.add(user)
    await session.flush()
    post = await forum_repo.create_post(
        session, user.id, PostCreate(title="t", body="b")
    )

    await forum_repo.set_vote(session, PostVote, user.id, post.id, 1)
    counts = await forum_repo.count_votes(session, PostVote, [post.id])
    assert counts[post.id] == (1, 0)

    # Same (user, post) again with the opposite value updates in place — the
    # unique constraint means a second insert would raise instead.
    await forum_repo.set_vote(session, PostVote, user.id, post.id, -1)
    counts = await forum_repo.count_votes(session, PostVote, [post.id])
    assert counts[post.id] == (0, 1)

    mine = await forum_repo.get_my_votes(session, PostVote, user.id, [post.id])
    assert mine == {post.id: -1}

    await forum_repo.remove_vote(session, PostVote, user.id, post.id)
    assert await forum_repo.count_votes(session, PostVote, [post.id]) == {}
    assert await forum_repo.get_my_votes(session, PostVote, user.id, [post.id]) == {}


# --- rate limiting ---
#
# On `committing_client`, so each request gets its own committing session and the
# limiter's independent counter session (patched onto the shared per-test
# connection) is visible across requests — the shared-session `client` fixture
# would keep everything in one uncommitted transaction. The transaction-boundary
# property (a failed request still counts) is proven at the service tier in
# unit.py; here we prove the routes are wired and return 429 + Retry-After.


async def test_login_is_rate_limited_per_ip(
    committing_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_login_max", 3)
    await signup_headers(committing_client, "rl@example.com", "s3cretpass")
    creds = {"username": "rl@example.com", "password": "s3cretpass"}

    for _ in range(3):
        ok = await committing_client.post("/auth/login", data=creds)
        assert ok.status_code == 200, ok.text

    limited = await committing_client.post("/auth/login", data=creds)
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers


async def test_analyze_is_rate_limited_per_user(
    committing_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_analyze_max", 2)
    headers = await signup_headers(committing_client, "rlu@example.com", "s3cretpass")
    user_id = auth.decode_access_token(headers["Authorization"].removeprefix("Bearer "))

    # Fill this user's analyze window to the limit directly — the same limiter the
    # route uses, so buckets match — without invoking the (slow) agent.
    for _ in range(2):
        await rate_limit_service.enforce(
            "analyze",
            str(user_id),
            settings.rate_limit_analyze_max,
            settings.rate_limit_analyze_window_seconds,
        )

    # The next /analyze trips the limiter in the dependency, before the agent runs.
    limited = await committing_client.post(
        "/analyze", json=ANALYZE_BODY, headers=headers
    )
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers


async def test_send_message_is_rate_limited(
    client: httpx.AsyncClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the limiter dependency is attached to the send route, not just
    defined — a dep that is never wired up would let all three through."""
    monkeypatch.setattr(settings, "rate_limit_message_max", 2)
    conversation_id = await _start_conversation(client, auth_headers)

    for _ in range(2):
        allowed = await client.post(
            f"/messages/conversations/{conversation_id}/messages",
            json={"body": "hi"},
            headers=auth_headers,
        )
        assert allowed.status_code == 201, allowed.text

    limited = await client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "hi"},
        headers=auth_headers,
    )
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers


async def test_start_conversation_is_rate_limited(
    client: httpx.AsyncClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opening threads has its own, tighter budget than sending into one."""
    monkeypatch.setattr(settings, "rate_limit_conversation_max", 1)
    await _start_conversation(client, auth_headers)

    limited = await client.post(
        "/messages/conversations",
        json={"recipient_email": "bob@example.com"},
        headers=auth_headers,
    )
    assert limited.status_code == 429


# --- direct messages ---


async def test_dm_round_trip(client: httpx.AsyncClient, auth_headers: dict) -> None:
    """Send from one account, read it from the other: inbox, preview, unread."""
    bob = await signup_headers(client, "bob@example.com")
    conversation_id = await _start_conversation(client, auth_headers)

    sent = await client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "hello bob"},
        headers=auth_headers,
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["sender_email"] == "alice@example.com"
    assert sent.json()["read_at"] is None

    inbox = (await client.get("/messages/conversations", headers=bob)).json()
    assert [c["id"] for c in inbox["items"]] == [conversation_id]
    entry = inbox["items"][0]
    # The far side of the pair, never both participants.
    assert entry["other_email"] == "alice@example.com"
    assert entry["last_message"]["body"] == "hello bob"
    assert entry["unread_count"] == 1
    assert (await client.get("/messages/unread", headers=bob)).json() == {
        "unread_count": 1
    }

    detail = (
        await client.get(f"/messages/conversations/{conversation_id}", headers=bob)
    ).json()
    assert [m["body"] for m in detail["messages"]] == ["hello bob"]

    read = await client.post(
        f"/messages/conversations/{conversation_id}/read", headers=bob
    )
    assert read.json() == {"marked_count": 1}
    assert (await client.get("/messages/unread", headers=bob)).json() == {
        "unread_count": 0
    }
    # Alice never had anything unread: her own message doesn't count for her.
    assert (await client.get("/messages/unread", headers=auth_headers)).json() == {
        "unread_count": 0
    }


async def test_dm_start_conversation_is_idempotent(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """A pair maps to one thread, so "message this person" always lands in it."""
    # bob signs up here, so _start_conversation's own signup attempt 409s — which
    # it tolerates.
    bob = await signup_headers(client, "bob@example.com")
    first = await _start_conversation(client, auth_headers)
    assert await _start_conversation(client, auth_headers) == first

    # And the recipient reaching back finds the same thread, from their side.
    from_bob = await client.post(
        "/messages/conversations",
        json={"recipient_email": "alice@example.com"},
        headers=bob,
    )
    assert from_bob.status_code == 201, from_bob.text
    assert from_bob.json()["id"] == first
    assert from_bob.json()["other_email"] == "alice@example.com"


async def test_dm_cannot_message_self_or_unknown_user(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    same = await client.post(
        "/messages/conversations",
        json={"recipient_email": "alice@example.com"},
        headers=auth_headers,
    )
    # 400, not a 500 from ck_conversations_user_order.
    assert same.status_code == 400, same.text

    ghost = await client.post(
        "/messages/conversations",
        json={"recipient_email": "ghost@example.com"},
        headers=auth_headers,
    )
    assert ghost.status_code == 404


async def test_dm_outsider_gets_404_not_403(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """403 would confirm two other people have a thread; ids are sequential, so
    a non-participant must not be able to tell existence from absence."""
    conversation_id = await _start_conversation(client, auth_headers)
    await client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "private"},
        headers=auth_headers,
    )
    outsider = await signup_headers(client, "cy@example.com")

    reads = [
        await client.get(
            f"/messages/conversations/{conversation_id}", headers=outsider
        ),
        await client.get(
            f"/messages/conversations/{conversation_id}/messages", headers=outsider
        ),
        await client.post(
            f"/messages/conversations/{conversation_id}/messages",
            json={"body": "intruding"},
            headers=outsider,
        ),
        await client.post(
            f"/messages/conversations/{conversation_id}/read", headers=outsider
        ),
    ]
    assert [r.status_code for r in reads] == [404, 404, 404, 404]

    # A conversation id that does not exist at all is indistinguishable.
    missing = await client.get(
        f"/messages/conversations/{conversation_id + 1000}", headers=outsider
    )
    assert missing.status_code == 404


async def test_dm_routes_require_auth(client: httpx.AsyncClient) -> None:
    for method, path, body in [
        ("get", "/messages/unread", None),
        ("get", "/messages/conversations", None),
        ("post", "/messages/conversations", {"recipient_email": "a@b.com"}),
        ("get", "/messages/conversations/1", None),
        ("get", "/messages/conversations/1/messages", None),
        ("post", "/messages/conversations/1/messages", {"body": "x"}),
        ("post", "/messages/conversations/1/read", None),
    ]:
        resp = await client.request(method, path, json=body)
        assert resp.status_code == 401, f"{method.upper()} {path} -> {resp.status_code}"


async def test_dm_thread_pages_newest_first(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    conversation_id = await _start_conversation(client, auth_headers)
    for i in range(3):
        await client.post(
            f"/messages/conversations/{conversation_id}/messages",
            json={"body": f"m{i}"},
            headers=auth_headers,
        )

    page = await client.get(
        f"/messages/conversations/{conversation_id}/messages",
        params={"limit": 2},
        headers=auth_headers,
    )
    body = page.json()
    assert [m["body"] for m in body["items"]] == ["m2", "m1"]
    assert body["next_cursor"] is not None

    older = await client.get(
        f"/messages/conversations/{conversation_id}/messages",
        params={"limit": 2, "cursor": body["next_cursor"]},
        headers=auth_headers,
    )
    assert [m["body"] for m in older.json()["items"]] == ["m0"]
    assert older.json()["next_cursor"] is None


async def test_dm_invalid_cursor_is_400(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    resp = await client.get(
        "/messages/conversations",
        params={"cursor": "not-a-cursor"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
