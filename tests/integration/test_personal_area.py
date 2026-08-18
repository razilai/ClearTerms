"""Integration tests: personal area (own posts + vote totals)."""


import httpx

from tests.conftest import signup_headers
from tests.integration.factories import _comment, _create_post

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
    assert totals == {
        "post_count": 2,
        "like_count": 2,
        "dislike_count": 1,
        "comment_count": 0,
        "comment_like_count": 0,
        "comment_dislike_count": 0,
    }


async def test_my_vote_totals_ignore_other_authors_posts(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    bobs_post = await _create_post(client, bob)
    await client.put(
        f"/forum/posts/{bobs_post}/vote", json={"value": 1}, headers=auth_headers
    )

    totals = (await client.get("/forum/me/vote-totals", headers=auth_headers)).json()
    assert totals == {
        "post_count": 0,
        "like_count": 0,
        "dislike_count": 0,
        "comment_count": 0,
        "comment_like_count": 0,
        "comment_dislike_count": 0,
    }


async def test_my_vote_totals_sums_votes_across_my_comments(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    first = await _comment(client, auth_headers, post_id, "First take")
    second = await _comment(client, auth_headers, post_id, "Second take")
    bob = await signup_headers(client, "bob@example.com")
    carol = await signup_headers(client, "carol@example.com")
    await client.put(f"/forum/comments/{first}/vote", json={"value": 1}, headers=bob)
    await client.put(f"/forum/comments/{first}/vote", json={"value": 1}, headers=carol)
    await client.put(f"/forum/comments/{second}/vote", json={"value": -1}, headers=bob)

    totals = (await client.get("/forum/me/vote-totals", headers=auth_headers)).json()
    assert totals["comment_count"] == 2
    assert totals["comment_like_count"] == 2
    assert totals["comment_dislike_count"] == 1
    # Comment votes must not leak into the post tally shown beside them.
    assert totals["like_count"] == 0
    assert totals["dislike_count"] == 0


async def test_my_vote_totals_ignore_other_authors_comments(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    bob = await signup_headers(client, "bob@example.com")
    bobs_comment = await _comment(client, bob, post_id, "Bob's take")
    await client.put(
        f"/forum/comments/{bobs_comment}/vote", json={"value": 1}, headers=auth_headers
    )

    totals = (await client.get("/forum/me/vote-totals", headers=auth_headers)).json()
    assert totals["comment_count"] == 0
    assert totals["comment_like_count"] == 0
    assert totals["comment_dislike_count"] == 0
