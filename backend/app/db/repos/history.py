from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HistoryEntry


async def append(
    session: AsyncSession, user_id: int, document_id: int, verdict: str
) -> HistoryEntry:
    raise NotImplementedError


async def list_for_user(session: AsyncSession, user_id: int) -> list[HistoryEntry]:
    raise NotImplementedError
