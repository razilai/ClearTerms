from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HistoryEntry


async def append(
    session: AsyncSession, user_id: int, document_id: int, verdict: str
) -> HistoryEntry:
    entry = HistoryEntry(user_id=user_id, document_id=document_id, verdict=verdict)
    session.add(entry)
    await session.flush()
    return entry

async def list_for_user(session: AsyncSession, user_id: int) -> list[HistoryEntry]:
    result = await session.execute(
        select(HistoryEntry)
        .where(HistoryEntry.user_id == user_id)
        .order_by(HistoryEntry.created_at.desc())
    )
    return list(result.scalars().all())
