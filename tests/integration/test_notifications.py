"""Notifications raised by forum and message activity, end to end."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import notifications as notifications_repo
from app.db.repos import users as users_repo
from tests.conftest import signup_headers
from tests.integration.factories import POST_BODY


async def _user_id(session: AsyncSession, email: str) -> int:
    user = await users_repo.get_by_email(session, email)
    assert user is not None
    return user.id


async def test_a_comment_notifies_the_post_author_only(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    resp = await client.post(
        f"/forum/posts/{post_id}/comments",
        json={"body": "good catch"},
        headers=bob,
    )
    assert resp.status_code == 201, resp.text

    alice_id = await _user_id(session, "alice@example.com")
    bob_id = await _user_id(session, "bob@example.com")
    rows = await notifications_repo.list_for_user(session, alice_id, 10)
    assert [(n.kind, n.actor_id, n.post_id) for n in rows] == [
        ("post_comment", bob_id, post_id)
    ]
    assert await notifications_repo.list_for_user(session, bob_id, 10) == []


async def test_two_comments_from_one_actor_are_two_notifications(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    """target_id is the comment id for this kind, so comments never collapse."""
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    for body in ("first", "second"):
        await client.post(
            f"/forum/posts/{post_id}/comments", json={"body": body}, headers=bob
        )

    alice_id = await _user_id(session, "alice@example.com")
    assert len(await notifications_repo.list_for_user(session, alice_id, 10)) == 2


async def test_commenting_on_your_own_post_is_silent(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    await client.post(
        f"/forum/posts/{post_id}/comments",
        json={"body": "replying to myself"},
        headers=auth_headers,
    )
    alice_id = await _user_id(session, "alice@example.com")
    assert await notifications_repo.list_for_user(session, alice_id, 10) == []


async def test_toggling_a_vote_leaves_exactly_one_notification(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    """Like, unlike, like again: the dedupe key is (actor, post), and clearing
    a vote emits nothing, so the author sees one event, not three."""
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    for value in (1, 1, 1):
        await client.put(
            f"/forum/posts/{post_id}/vote", json={"value": value}, headers=bob
        )

    alice_id = await _user_id(session, "alice@example.com")
    rows = await notifications_repo.list_for_user(session, alice_id, 10)
    assert len(rows) == 1
    assert rows[0].kind == "post_vote"
    assert rows[0].value == 1


async def test_a_comment_vote_notifies_the_comment_author(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    comment_id = (
        await client.post(
            f"/forum/posts/{post_id}/comments", json={"body": "hi"}, headers=bob
        )
    ).json()["id"]
    resp = await client.put(
        f"/forum/comments/{comment_id}/vote", json={"value": -1}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    bob_id = await _user_id(session, "bob@example.com")
    rows = await notifications_repo.list_for_user(session, bob_id, 10)
    # The comment vote, plus nothing else: alice owns the post, so bob's
    # comment on it notified her, not him.
    assert [(n.kind, n.value, n.post_id) for n in rows] == [
        ("comment_vote", -1, post_id)
    ]


async def test_deleting_a_post_cascades_its_notifications_away(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    await client.put(f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=bob)
    alice_id = await _user_id(session, "alice@example.com")
    assert len(await notifications_repo.list_for_user(session, alice_id, 10)) == 1

    resp = await client.delete(f"/forum/posts/{post_id}", headers=auth_headers)
    assert resp.status_code == 204, resp.text
    session.expire_all()
    assert await notifications_repo.list_for_user(session, alice_id, 10) == []
