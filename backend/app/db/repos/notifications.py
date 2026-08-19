"""Notification data access.

The upsert is the whole design: one INSERT ... ON CONFLICT keyed on
uq_notifications_event, so whether a repeated event collapses is decided by
what the caller puts in target_id, not by branching here.
"""

from datetime import datetime
from typing import cast

from sqlalchemy import CursorResult, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.util import identity_key

from app.models import Notification


async def upsert(
    session: AsyncSession,
    *,
    recipient_id: int,
    actor_id: int,
    kind: str,
    target_id: int,
    value: int | None = None,
    post_id: int | None = None,
    comment_id: int | None = None,
    conversation_id: int | None = None,
) -> None:
    """Record the event, or refresh the existing row for the same event.

    On conflict the row is bumped to now, its value rewritten (a like -> dislike
    flip re-notifies with the new verb) and read_at cleared so it resurfaces.
    The foreign keys are not in the update set: they describe the same event
    and cannot have changed.

    ``func.now()`` is Postgres' transaction timestamp, not the wall clock, so
    an insert and a later conflicting update in the *same* transaction land on
    the same created_at. That is exactly right for real requests, which are one
    transaction each — but it means a test running both inside the per-test
    transaction must assert on value and read_at, never on created_at moving.
    """
    stmt = (
        pg_insert(Notification)
        .values(
            recipient_id=recipient_id,
            actor_id=actor_id,
            kind=kind,
            target_id=target_id,
            value=value,
            post_id=post_id,
            comment_id=comment_id,
            conversation_id=conversation_id,
        )
        .on_conflict_do_update(
            constraint="uq_notifications_event",
            set_={"value": value, "created_at": func.now(), "read_at": None},
        )
        .returning(Notification.id)
    )
    result = await session.execute(stmt)
    await session.flush()
    # ON CONFLICT rewrites columns behind the ORM's back, so an instance this
    # session already holds would keep serving its pre-conflict values — the
    # identity map wins over a later SELECT. Expire just that row so the next
    # read reloads it. Only ever a no-op in production, where emitting and
    # reading a notification are different requests.
    stale = session.sync_session.identity_map.get(
        identity_key(Notification, result.scalar_one())
    )
    if stale is not None:
        session.expire(stale)


async def list_for_user(
    session: AsyncSession,
    user_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None = None,
) -> list[Notification]:
    """One keyset page of a user's notifications, newest first.

    Fetches ``limit + 1`` so the caller can detect a further page; uses
    ``ix_notifications_recipient_created_id``.
    """
    stmt = select(Notification).where(Notification.recipient_id == user_id)
    if cursor is not None:
        stmt = stmt.where(tuple_(Notification.created_at, Notification.id) < cursor)
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(
        limit + 1
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_unread(session: AsyncSession, user_id: int) -> int:
    """Every unacknowledged notification, regardless of which page is on screen."""
    result = await session.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_id == user_id, Notification.read_at.is_(None))
    )
    return result.scalar_one()


async def get(session: AsyncSession, notification_id: int) -> Notification | None:
    return await session.get(Notification, notification_id)


async def mark_read(session: AsyncSession, notification_id: int, when: datetime) -> None:
    """Acknowledge one notification. Already-read rows keep their read_at."""
    await session.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.read_at.is_(None))
        .values(read_at=when)
    )
    await session.flush()


async def mark_all_read(session: AsyncSession, user_id: int, when: datetime) -> int:
    """Acknowledge everything this user has. Returns how many rows changed."""
    result = await session.execute(
        update(Notification)
        .where(Notification.recipient_id == user_id, Notification.read_at.is_(None))
        .values(read_at=when)
    )
    await session.flush()
    return cast("CursorResult[object]", result).rowcount
