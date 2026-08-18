"""Integration tests: post and comment votes."""


import httpx

from tests.conftest import signup_headers
from tests.integration.factories import _create_post, _post_and_comment

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
