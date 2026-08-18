"""Integration tests for direct-message routes."""

import httpx
import pytest

from app.core.config import settings
from tests.conftest import signup_headers

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _start_conversation(
    client: httpx.AsyncClient, headers: dict, recipient: str = "bob@example.com"
) -> int:
    signup = await client.post(
        "/auth/signup", json={"email": recipient, "password": "hunter2!"}
    )
    assert signup.status_code in (201, 409), signup.text
    response = await client.post(
        "/messages/conversations", json={"recipient_email": recipient}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_dm_round_trip_marks_messages_read(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    conversation_id = await _start_conversation(client, auth_headers)
    sent = await client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "hello bob"},
        headers=auth_headers,
    )
    assert sent.status_code == 201
    inbox = (await client.get("/messages/conversations", headers=bob)).json()
    assert inbox["items"][0]["other_email"] == "alice@example.com"
    assert inbox["items"][0]["last_message"]["body"] == "hello bob"
    assert inbox["items"][0]["unread_count"] == 1
    assert (await client.get("/messages/unread", headers=bob)).json() == {
        "unread_count": 1
    }
    read = await client.post(
        f"/messages/conversations/{conversation_id}/read", headers=bob
    )
    assert read.json() == {"marked_count": 1}
    assert (await client.get("/messages/unread", headers=bob)).json() == {
        "unread_count": 0
    }


async def test_dm_start_is_idempotent_and_rejects_self_or_unknown_user(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    bob = await signup_headers(client, "bob@example.com")
    first = await _start_conversation(client, auth_headers)
    assert await _start_conversation(client, auth_headers) == first
    reverse = await client.post(
        "/messages/conversations",
        json={"recipient_email": "alice@example.com"},
        headers=bob,
    )
    assert reverse.json()["id"] == first
    self_response = await client.post(
        "/messages/conversations",
        json={"recipient_email": "alice@example.com"},
        headers=auth_headers,
    )
    unknown_response = await client.post(
        "/messages/conversations",
        json={"recipient_email": "missing@example.com"},
        headers=auth_headers,
    )
    assert self_response.status_code == 400
    assert unknown_response.status_code == 404


async def test_dm_cannot_create_a_phantom_thread_for_an_unknown_recipient(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """Only registered users may become the other participant in a DM."""
    response = await client.post(
        "/messages/conversations",
        json={"recipient_email": "nobody@example.com"},
        headers=auth_headers,
    )

    assert response.status_code == 404
    inbox = await client.get("/messages/conversations", headers=auth_headers)
    assert inbox.status_code == 200
    assert inbox.json()["items"] == []


async def test_dm_non_participant_cannot_discover_a_conversation(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    conversation_id = await _start_conversation(client, auth_headers)
    outsider = await signup_headers(client, "cy@example.com")
    responses = [
        await client.get(
            f"/messages/conversations/{conversation_id}", headers=outsider
        ),
        await client.get(
            f"/messages/conversations/{conversation_id}/messages", headers=outsider
        ),
        await client.post(
            f"/messages/conversations/{conversation_id}/read", headers=outsider
        ),
    ]
    assert [response.status_code for response in responses] == [404, 404, 404]


async def test_dm_thread_pages_and_invalid_cursor(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    conversation_id = await _start_conversation(client, auth_headers)
    for index in range(3):
        response = await client.post(
            f"/messages/conversations/{conversation_id}/messages",
            json={"body": f"m{index}"},
            headers=auth_headers,
        )
        assert response.status_code == 201
    first = await client.get(
        f"/messages/conversations/{conversation_id}/messages",
        params={"limit": 2},
        headers=auth_headers,
    )
    assert [message["body"] for message in first.json()["items"]] == ["m2", "m1"]
    second = await client.get(
        f"/messages/conversations/{conversation_id}/messages",
        params={"limit": 2, "cursor": first.json()["next_cursor"]},
        headers=auth_headers,
    )
    assert [message["body"] for message in second.json()["items"]] == ["m0"]
    bad_cursor = await client.get(
        "/messages/conversations", params={"cursor": "bad"}, headers=auth_headers
    )
    assert bad_cursor.status_code == 400


async def test_message_attachment_round_trip_and_empty_body_policy(
    committing_client: httpx.AsyncClient, fake_storage: dict
) -> None:
    alice = await signup_headers(committing_client, "alice-dm@example.com")
    bob = await signup_headers(committing_client, "bob-dm@example.com")
    conversation_id = await _start_conversation(
        committing_client, alice, "bob-dm@example.com"
    )
    attachment = await committing_client.post(
        "/forum/attachments",
        files={"file": ("image.png", _TINY_PNG, "image/png")},
        headers=alice,
    )
    attachment_id = attachment.json()["id"]
    empty = await committing_client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "   "},
        headers=alice,
    )
    assert empty.status_code == 400
    sent = await committing_client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "", "attachment_ids": [attachment_id]},
        headers=alice,
    )
    assert sent.status_code == 201
    detail = await committing_client.get(
        f"/messages/conversations/{conversation_id}", headers=bob
    )
    assert [item["id"] for item in detail.json()["messages"][0]["attachments"]] == [
        attachment_id
    ]


async def test_dm_routes_require_auth_and_enforce_rate_limits(
    client: httpx.AsyncClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await client.get("/messages/unread")).status_code == 401
    assert (
        await client.post(
            "/messages/conversations", json={"recipient_email": "a@b.com"}
        )
    ).status_code == 401
    monkeypatch.setattr(settings, "rate_limit_message_max", 1)
    conversation_id = await _start_conversation(client, auth_headers)
    first = await client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "one"},
        headers=auth_headers,
    )
    limited = await client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "two"},
        headers=auth_headers,
    )
    assert first.status_code == 201
    assert limited.status_code == 429
