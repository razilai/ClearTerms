from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HistoryEntry


async def append(
    session: AsyncSession, user_id: int, document_id: int, verdict: str
) -> HistoryEntry:
    entry = HistoryEntry(user_id=user_id, document_id=document_id, verdict=verdict)
    session.add(entry)
    await session.flush()
    return entry


async def list_for_user(
    session: AsyncSession,
    user_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None = None,
) -> list[HistoryEntry]:
    """One keyset page, newest first. Fetches ``limit + 1`` so the caller can
    tell whether a further page exists. ``cursor`` is the last-seen
    ``(created_at, id)``; rows strictly before it come next. Uses the
    ``ix_history_user_created`` composite index.
    """
    stmt = select(HistoryEntry).where(HistoryEntry.user_id == user_id)
    if cursor is not None:
        stmt = stmt.where(
            tuple_(HistoryEntry.created_at, HistoryEntry.id) < cursor
        )
    stmt = stmt.order_by(
        HistoryEntry.created_at.desc(), HistoryEntry.id.desc()
    ).limit(limit + 1)
    result = await session.execute(stmt)
    return list(result.scalars().all())
