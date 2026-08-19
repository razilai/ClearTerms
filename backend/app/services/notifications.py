"""Notification business logic.

``emit`` is the write side, called by the forum and messages services on their
own session so a rolled-back action cannot leave a phantom notification. The
read side returns API schemas, not ORM rows, because actor emails and post
titles have to be joined in — db work the api layer is not allowed to do
(mirrors the forum and messages services).
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import forum as forum_repo
from app.db.repos import notifications as notifications_repo
from app.db.repos import users as users_repo
from app.schemas.notifications import (
    MarkAllReadResponse,
    NotificationKind,
    NotificationOut,
    NotificationPage,
)
from app.schemas.pagination import slice_page
from app.services.exceptions import NotFoundError


async def emit(
    session: AsyncSession,
    *,
    recipient_id: int,
    actor_id: int,
    kind: NotificationKind,
    target_id: int,
    value: int | None = None,
    post_id: int | None = None,
    comment_id: int | None = None,
    conversation_id: int | None = None,
) -> None:
    """Record an event for the recipient, unless they caused it themselves.

    The self-check lives here rather than at each call site so that commenting
    on your own post, or voting your own content, is silent everywhere by
    construction.
    """
    if recipient_id == actor_id:
        return
    await notifications_repo.upsert(
        session,
        recipient_id=recipient_id,
        actor_id=actor_id,
        kind=kind,
        target_id=target_id,
        value=value,
        post_id=post_id,
        comment_id=comment_id,
        conversation_id=conversation_id,
    )


async def list_notifications(
    session: AsyncSession,
    user_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None,
) -> NotificationPage:
    """One keyset page, newest first, plus the unread total.

    Three batched queries for the page: actor emails, post titles, and the
    count — no per-row lookups.
    """
    rows = await notifications_repo.list_for_user(session, user_id, limit, cursor)
    rows, next_cursor = slice_page(rows, limit, lambda n: (n.created_at, n.id))
    emails = await users_repo.get_emails(session, {n.actor_id for n in rows})
    titles = await forum_repo.get_post_titles(
        session, {n.post_id for n in rows if n.post_id is not None}
    )
    items = [
        NotificationOut(
            id=n.id,
            kind=n.kind,  # type: ignore[arg-type]
            actor_email=emails[n.actor_id],
            value=n.value,
            post_id=n.post_id,
            post_title=titles.get(n.post_id) if n.post_id is not None else None,
            conversation_id=n.conversation_id,
            created_at=n.created_at,
            read_at=n.read_at,
        )
        for n in rows
    ]
    return NotificationPage(
        items=items,
        next_cursor=next_cursor,
        unread_count=await notifications_repo.count_unread(session, user_id),
    )


async def mark_read(session: AsyncSession, user_id: int, notification_id: int) -> None:
    """Acknowledge one notification.

    Someone else's id raises NotFoundError, not NotOwnerError: notification ids
    are sequential, so a 403 would confirm that a given event exists.
    """
    notification = await notifications_repo.get(session, notification_id)
    if notification is None or notification.recipient_id != user_id:
        raise NotFoundError("notification")
    await notifications_repo.mark_read(session, notification_id, datetime.now(tz=UTC))


async def mark_all_read(session: AsyncSession, user_id: int) -> MarkAllReadResponse:
    return MarkAllReadResponse(
        marked_count=await notifications_repo.mark_all_read(
            session, user_id, datetime.now(tz=UTC)
        )
    )
