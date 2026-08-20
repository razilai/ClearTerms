"""Integration tests: attachment upload, processing, and cleanup."""


import httpx
import pytest

from app.core.config import settings
from tests.conftest import signup_headers
from tests.integration.factories import POST_BODY

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


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


async def test_attachment_read_requires_visibility(
    committing_client: httpx.AsyncClient,
    fake_storage: dict,
) -> None:
    """An unlinked upload is readable only by the uploader.

    Without this the id space is enumerable: any authenticated account could
    walk /forum/attachments/{id} and collect presigned URLs for media it has no
    route to otherwise.
    """
    alice = await signup_headers(committing_client, "alice-vis@example.com")
    mallory = await signup_headers(committing_client, "mallory-vis@example.com")
    att_id, _ = await _upload_png(committing_client, alice)

    assert (
        await committing_client.get(
            f"/forum/attachments/{att_id}", headers=alice
        )
    ).status_code == 200
    outsider = await committing_client.get(
        f"/forum/attachments/{att_id}", headers=mallory
    )
    # 404 rather than 403 so the response does not confirm the id exists.
    assert outsider.status_code == 404


async def test_attachment_on_a_post_is_readable_by_anyone(
    committing_client: httpx.AsyncClient,
    fake_storage: dict,
) -> None:
    """Posts are public, so their attachments stay readable to other users."""
    alice = await signup_headers(committing_client, "alice-pub@example.com")
    bob = await signup_headers(committing_client, "bob-pub@example.com")
    att_id, _ = await _upload_png(committing_client, alice)
    created = await committing_client.post(
        "/forum/posts",
        json={**POST_BODY, "attachment_ids": [att_id]},
        headers=alice,
    )
    assert created.status_code == 201, created.text

    resp = await committing_client.get(
        f"/forum/attachments/{att_id}", headers=bob
    )
    assert resp.status_code == 200


async def test_message_attachment_visible_to_participants_only(
    committing_client: httpx.AsyncClient,
    fake_storage: dict,
) -> None:
    """Both sides of a conversation may read its attachments; nobody else may.

    The recipient is covered deliberately: message reads currently deliver
    attachments inline, but the rule has to hold if the client starts polling
    this route for media it did not upload.
    """
    alice = await signup_headers(committing_client, "alice-dm-vis@example.com")
    bob = await signup_headers(committing_client, "bob-dm-vis@example.com")
    outsider = await signup_headers(committing_client, "cy-dm-vis@example.com")

    conversation_id = (
        await committing_client.post(
            "/messages/conversations",
            json={"recipient_email": "bob-dm-vis@example.com"},
            headers=alice,
        )
    ).json()["id"]
    att_id, _ = await _upload_png(committing_client, alice)
    sent = await committing_client.post(
        f"/messages/conversations/{conversation_id}/messages",
        json={"body": "private", "attachment_ids": [att_id]},
        headers=alice,
    )
    assert sent.status_code == 201, sent.text

    for headers, expected in ((alice, 200), (bob, 200), (outsider, 404)):
        resp = await committing_client.get(
            f"/forum/attachments/{att_id}", headers=headers
        )
        assert resp.status_code == expected


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


async def test_upload_unsupported_type(
    client: httpx.AsyncClient,
    auth_headers: dict,
    fake_storage: dict,
) -> None:
    files = {"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")}
    resp = await client.post("/forum/attachments", files=files, headers=auth_headers)
    assert resp.status_code == 415


async def test_upload_sniffs_bytes_not_the_declared_content_type(
    client: httpx.AsyncClient,
    auth_headers: dict,
    fake_storage: dict,
) -> None:
    """A non-image renamed .png and declared image/png is still rejected —
    validation reads the actual bytes, so a spoofed Content-Type cannot smuggle
    a disallowed type past the image whitelist."""
    files = {"file": ("evil.png", b"%PDF-1.4 not an image at all", "image/png")}
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
