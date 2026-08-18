"""Integration tests: anonymous posts and inherited comment anonymity."""


import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import forum as forum_repo
from app.models import CommentVote, PostVote
from tests.conftest import signup_headers
from tests.integration.factories import (
    POST_BODY,
    _comment,
    _create_post,
    _post_and_comment,
)

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
