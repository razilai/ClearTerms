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


async def test_every_dm_notifies_the_recipient_separately(
    client: httpx.AsyncClient, session: AsyncSession, auth_headers: dict[str, str]
) -> None:
    """target_id is the message id, so a chatty sender produces one
    notification per message rather than one per thread."""
    bob = await signup_headers(client, "bob@example.com")
    conversation_id = (
        await client.post(
            "/messages/conversations",
            json={"recipient_email": "alice@example.com"},
            headers=bob,
        )
    ).json()["id"]
    for body in ("hello", "you there?"):
        resp = await client.post(
            f"/messages/conversations/{conversation_id}/messages",
            json={"body": body},
            headers=bob,
        )
        assert resp.status_code == 201, resp.text

    alice_id = await _user_id(session, "alice@example.com")
    bob_id = await _user_id(session, "bob@example.com")
    rows = await notifications_repo.list_for_user(session, alice_id, 10)
    assert len(rows) == 2
    assert {n.kind for n in rows} == {"dm"}
    assert {n.conversation_id for n in rows} == {conversation_id}
    assert all(n.post_id is None for n in rows)
    assert await notifications_repo.list_for_user(session, bob_id, 10) == []


async def test_the_feed_names_the_actor_and_carries_the_post_title(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    await client.put(f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=bob)

    resp = await client.get("/notifications?limit=15", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["unread_count"] == 1
    item = payload["items"][0]
    assert item["kind"] == "post_vote"
    assert item["actor_email"] == "bob@example.com"
    assert item["value"] == 1
    assert item["post_id"] == post_id
    assert item["post_title"] == POST_BODY["title"]
    assert item["conversation_id"] is None
    assert item["read_at"] is None


async def test_marking_one_read_clears_it_from_the_unread_count(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    await client.post(
        f"/forum/posts/{post_id}/comments", json={"body": "hi"}, headers=bob
    )
    notification_id = (
        await client.get("/notifications", headers=auth_headers)
    ).json()["items"][0]["id"]

    resp = await client.post(
        f"/notifications/{notification_id}/read", headers=auth_headers
    )
    assert resp.status_code == 204, resp.text
    payload = (await client.get("/notifications", headers=auth_headers)).json()
    assert payload["unread_count"] == 0
    assert payload["items"][0]["read_at"] is not None


async def test_marking_someone_elses_notification_read_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    await client.post(
        f"/forum/posts/{post_id}/comments", json={"body": "hi"}, headers=bob
    )
    notification_id = (
        await client.get("/notifications", headers=auth_headers)
    ).json()["items"][0]["id"]

    resp = await client.post(f"/notifications/{notification_id}/read", headers=bob)
    assert resp.status_code == 404, resp.text


async def test_mark_all_read_reports_what_it_changed(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    for body in ("one", "two"):
        await client.post(
            f"/forum/posts/{post_id}/comments", json={"body": body}, headers=bob
        )

    resp = await client.post("/notifications/read", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"marked_count": 2}
    assert (
        await client.get("/notifications", headers=auth_headers)
    ).json()["unread_count"] == 0


async def test_the_feed_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/notifications")).status_code == 401


async def test_the_feed_pages_by_cursor(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    post_id = (
        await client.post("/forum/posts", json=POST_BODY, headers=auth_headers)
    ).json()["id"]
    for body in ("one", "two", "three"):
        await client.post(
            f"/forum/posts/{post_id}/comments", json={"body": body}, headers=bob
        )

    first = (
        await client.get("/notifications?limit=2", headers=auth_headers)
    ).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None
    second = (
        await client.get(
            f"/notifications?limit=2&cursor={first['next_cursor']}",
            headers=auth_headers,
        )
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
