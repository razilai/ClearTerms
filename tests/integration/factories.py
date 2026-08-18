"""Shared factories for the integration tier: request helpers + bodies."""


import httpx

POST_BODY = {"title": "Sneaky arbitration clause", "body": "Section 12 forces arbitration."}


ANALYZE_BODY = {"text": "You agree to binding arbitration.", "url": "https://ex.test/tos"}


async def _create_post(client: httpx.AsyncClient, headers: dict) -> int:
    resp = await client.post("/forum/posts", json=POST_BODY, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _comment(client: httpx.AsyncClient, headers: dict, post_id: int, body: str) -> int:
    resp = await client.post(
        f"/forum/posts/{post_id}/comments", json={"body": body}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


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
