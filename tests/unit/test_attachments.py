"""Unit tests: attachment upload service (validation, ordering, orphan sweep)."""

import io
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import Headers, UploadFile

from app.core.config import settings
from app.db import engine as engine_module
from app.db.repos import attachments as attachments_repo
from app.db.repos import forum as forum_repo
from app.db.repos import users as users_repo
from app.models import Attachment
from app.schemas.forum import PostCreate
from app.services import forum as forum_service
from app.services import media as media_service
from app.services.exceptions import FileTooLargeError, UnsupportedMediaTypeError

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


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

    Service-level (no HTTP): the shared-connection test harness can't reproduce
    the cross-connection invisibility, so this asserts the ordering directly. At
    the moment the task is scheduled the session must no longer be in a
    transaction (i.e. it has committed). ``in_transaction()`` is True after a
    flush, False after commit.
    """
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


# --- upload validation ------------------------------------------------------
#
# validate_upload sniffs the real MIME from the bytes and never trusts the
# declared Content-Type; the byte-vs-header spoof case is covered over HTTP in
# integration/test_attachments.py. Here we drive the video branch (which the
# HTTP tests never reach — crafting valid video magic bytes plus ffprobe is not
# worth it) by stubbing the sniff and the duration probe.


def _upload(mime: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(b"x" * 100),
        filename="clip",
        headers=Headers({"content-type": mime}),
    )


async def test_validate_upload_accepts_a_video_within_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_service, "_sniff_mime", lambda data: "video/mp4")

    async def _probe(data: bytes, mime: str) -> float:
        return 10.0

    monkeypatch.setattr(media_service, "_probe_duration", _probe)

    media_type, real_mime = await media_service.validate_upload(
        _upload("video/mp4"), b"x" * 100
    )
    assert media_type == "video"
    assert real_mime == "video/mp4"


async def test_validate_upload_rejects_a_video_over_the_duration_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The duration cap is a distinct branch from the byte-size cap — an
    otherwise small file can still be too long."""
    monkeypatch.setattr(media_service, "_sniff_mime", lambda data: "video/mp4")

    async def _too_long(data: bytes, mime: str) -> float:
        return float(settings.max_video_duration_seconds + 1)

    monkeypatch.setattr(media_service, "_probe_duration", _too_long)

    with pytest.raises(FileTooLargeError):
        await media_service.validate_upload(_upload("video/mp4"), b"x" * 100)


async def test_validate_upload_rejects_unrecognised_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_service, "_sniff_mime", lambda data: None)
    with pytest.raises(UnsupportedMediaTypeError):
        await media_service.validate_upload(_upload("image/png"), b"not a real file")


# --- orphan sweep -----------------------------------------------------------
#
# sweep_orphans opens its OWN session from the global SessionFactory (it runs
# out of band), so it needs a committing factory on an independent connection —
# the shared-connection `session` harness would hide the cross-session read.
# file_session_factory provides that; patch the global SessionFactory onto it so
# the sweep and the setup share one throwaway database.


async def test_sweep_orphans_deletes_only_old_unlinked_attachments(
    file_session_factory: async_sessionmaker[AsyncSession],
    fake_storage: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_module, "SessionFactory", file_session_factory)

    old = datetime.now(UTC) - timedelta(hours=48)
    recent = datetime.now(UTC)

    async with file_session_factory() as s:
        user = await users_repo.create(s, "sweeper@example.com", "hash")
        post = await forum_repo.create_post(
            s, user.id, PostCreate(title="t", body="b")
        )

        async def _make(key: str, *, created: datetime, post_id: int | None) -> int:
            a = await attachments_repo.create(
                s,
                user_id=user.id,
                media_type="image",
                mime="image/png",
                size_bytes=10,
                original_key=key,
            )
            a.created_at = created
            a.post_id = post_id
            fake_storage[key] = b"blob"
            return a.id

        old_orphan = await _make("k/old-orphan", created=old, post_id=None)
        recent_orphan = await _make("k/recent-orphan", created=recent, post_id=None)
        linked = await _make("k/linked", created=old, post_id=post.id)
        await s.commit()

    # Cutoff at 24h: only the 48h-old *unlinked* attachment qualifies.
    removed = await media_service.sweep_orphans(older_than_seconds=86_400.0)
    assert removed == 1

    async with file_session_factory() as verify:
        surviving = set(
            (await verify.execute(select(Attachment.id))).scalars().all()
        )
    assert surviving == {recent_orphan, linked}
    assert old_orphan not in surviving

    # The swept attachment's object is gone; the survivors' objects remain.
    assert "k/old-orphan" not in fake_storage
    assert "k/recent-orphan" in fake_storage
    assert "k/linked" in fake_storage
