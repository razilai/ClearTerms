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


# --- voter lists (owner-only) ---


async def test_post_author_sees_who_voted_split_by_side(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    bob = await signup_headers(client, "bob@example.com")
    cy = await signup_headers(client, "cy@example.com")
    await client.put(f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=bob)
    await client.put(f"/forum/posts/{post_id}/vote", json={"value": -1}, headers=cy)

    resp = await client.get(f"/forum/posts/{post_id}/votes", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert {(v["email"], v["value"]) for v in items} == {
        ("bob@example.com", 1),
        ("cy@example.com", -1),
    }

    likes = await client.get(
        f"/forum/posts/{post_id}/votes?value=1", headers=auth_headers
    )
    assert [v["email"] for v in likes.json()["items"]] == ["bob@example.com"]
    dislikes = await client.get(
        f"/forum/posts/{post_id}/votes?value=-1", headers=auth_headers
    )
    assert [v["email"] for v in dislikes.json()["items"]] == ["cy@example.com"]


async def test_a_non_author_cannot_see_who_voted_on_a_post(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """403, not 404: the post itself is public, only the voter list is not."""
    post_id = await _create_post(client, auth_headers)
    bob = await signup_headers(client, "bob@example.com")
    await client.put(f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=bob)

    resp = await client.get(f"/forum/posts/{post_id}/votes", headers=bob)
    assert resp.status_code == 403, resp.text


async def test_comment_author_sees_their_own_comment_voters(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """Ownership follows the voted-on thing: the comment's author, not the
    author of the post it sits under."""
    post_id = await _create_post(client, auth_headers)
    bob = await signup_headers(client, "bob@example.com")
    comment_id = (
        await client.post(
            f"/forum/posts/{post_id}/comments", json={"body": "hi"}, headers=bob
        )
    ).json()["id"]
    await client.put(
        f"/forum/comments/{comment_id}/vote", json={"value": 1}, headers=auth_headers
    )

    mine = await client.get(f"/forum/comments/{comment_id}/votes", headers=bob)
    assert mine.status_code == 200, mine.text
    assert [v["email"] for v in mine.json()["items"]] == ["alice@example.com"]

    # Alice owns the post but not the comment, so the comment's voters are
    # not hers to see.
    theirs = await client.get(
        f"/forum/comments/{comment_id}/votes", headers=auth_headers
    )
    assert theirs.status_code == 403, theirs.text


async def test_voter_list_requires_auth_and_404s_for_a_missing_post(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    assert (await client.get("/forum/posts/1/votes")).status_code == 401
    resp = await client.get("/forum/posts/999999/votes", headers=auth_headers)
    assert resp.status_code == 404, resp.text


async def test_voter_list_pages_by_cursor(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    post_id = await _create_post(client, auth_headers)
    for name in ("bob", "cy", "dee"):
        voter = await signup_headers(client, f"{name}@example.com")
        await client.put(
            f"/forum/posts/{post_id}/vote", json={"value": 1}, headers=voter
        )

    first = (
        await client.get(f"/forum/posts/{post_id}/votes?limit=2", headers=auth_headers)
    ).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None
    second = (
        await client.get(
            f"/forum/posts/{post_id}/votes?limit=2&cursor={first['next_cursor']}",
            headers=auth_headers,
        )
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    seen = [v["email"] for v in first["items"] + second["items"]]
    assert len(set(seen)) == 3
