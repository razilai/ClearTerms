"""Attachment data access."""

from collections.abc import Iterable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment


async def create(
    session: AsyncSession,
    *,
    user_id: int,
    media_type: str,
    mime: str,
    size_bytes: int,
    original_key: str,
) -> Attachment:
    attachment = Attachment(
        user_id=user_id,
        media_type=media_type,
        status="pending",
        mime=mime,
        size_bytes=size_bytes,
        original_key=original_key,
    )
    session.add(attachment)
    await session.flush()
    return attachment


async def get(session: AsyncSession, attachment_id: int) -> Attachment | None:
    return await session.get(Attachment, attachment_id)


async def get_by_ids(
    session: AsyncSession, ids: Iterable[int]
) -> list[Attachment]:
    id_list = list(ids)
    if not id_list:
        return []
    result = await session.execute(
        select(Attachment).where(Attachment.id.in_(id_list))
    )
    return list(result.scalars().all())


async def list_for_posts(
    session: AsyncSession, post_ids: Iterable[int]
) -> dict[int, list[Attachment]]:
    """Map post_id -> attachments; mirrors count_likes_by_post to avoid N+1."""
    ids = list(post_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(Attachment).where(Attachment.post_id.in_(ids))
    )
    rows = result.scalars().all()
    out: dict[int, list[Attachment]] = {}
    for a in rows:
        out.setdefault(a.post_id, []).append(a)  # type: ignore[arg-type]
    return out


async def list_for_comments(
    session: AsyncSession, comment_ids: Iterable[int]
) -> dict[int, list[Attachment]]:
    """Map comment_id -> attachments."""
    ids = list(comment_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(Attachment).where(Attachment.comment_id.in_(ids))
    )
    rows = result.scalars().all()
    out: dict[int, list[Attachment]] = {}
    for a in rows:
        out.setdefault(a.comment_id, []).append(a)  # type: ignore[arg-type]
    return out


async def _claim(
    session: AsyncSession,
    ids: list[int],
    user_id: int,
    *,
    post_id: int | None = None,
    comment_id: int | None = None,
) -> list[Attachment]:
    """Link unlinked, user-owned attachments to a post or comment.

    Returns all fetched rows. Caller detects mismatch by comparing the returned
    set to the requested ids.
    """
    if not ids:
        return []
    result = await session.execute(select(Attachment).where(Attachment.id.in_(ids)))
    rows = list(result.scalars().all())
    for a in rows:
        if a.user_id != user_id or a.post_id is not None or a.comment_id is not None:
            return rows  # service will detect the mismatch
        a.post_id = post_id
        a.comment_id = comment_id
    await session.flush()
    return rows


async def claim_for_post(
    session: AsyncSession, ids: list[int], user_id: int, post_id: int
) -> list[Attachment]:
    return await _claim(session, ids, user_id, post_id=post_id)


async def claim_for_comment(
    session: AsyncSession, ids: list[int], user_id: int, comment_id: int
) -> list[Attachment]:
    return await _claim(session, ids, user_id, comment_id=comment_id)


async def set_ready(
    session: AsyncSession,
    attachment_id: int,
    *,
    display_key: str,
    thumbnail_key: str,
    width: int | None,
    height: int | None,
    duration_seconds: float | None,
) -> None:
    await session.execute(
        update(Attachment)
        .where(Attachment.id == attachment_id)
        .values(
            status="ready",
            display_key=display_key,
            thumbnail_key=thumbnail_key,
            width=width,
            height=height,
            duration_seconds=duration_seconds,
        )
    )
    await session.flush()


async def set_failed(session: AsyncSession, attachment_id: int) -> None:
    await session.execute(
        update(Attachment)
        .where(Attachment.id == attachment_id)
        .values(status="failed")
    )
    await session.flush()


def _attachment_keys(attachments: list[Attachment]) -> list[str]:
    return [
        k
        for a in attachments
        for k in [a.original_key, a.display_key, a.thumbnail_key]
        if k is not None
    ]


async def keys_for_post(session: AsyncSession, post_id: int) -> list[str]:
    result = await session.execute(select(Attachment).where(Attachment.post_id == post_id))
    return _attachment_keys(list(result.scalars().all()))


async def keys_for_comment(session: AsyncSession, comment_id: int) -> list[str]:
    result = await session.execute(
        select(Attachment).where(Attachment.comment_id == comment_id)
    )
    return _attachment_keys(list(result.scalars().all()))


async def list_unlinked_before(
    session: AsyncSession, before_epoch: float
) -> list[Attachment]:
    """Orphan sweep: attachments with no post/comment older than a timestamp."""
    from datetime import UTC, datetime

    cutoff = datetime.fromtimestamp(before_epoch, tz=UTC)
    result = await session.execute(
        select(Attachment).where(
            Attachment.post_id.is_(None),
            Attachment.comment_id.is_(None),
            Attachment.created_at < cutoff,
        )
    )
    return list(result.scalars().all())
