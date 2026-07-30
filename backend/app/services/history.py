"""Per-user history of analyzed TOS documents."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HistoryEntry


async def list_history(session: AsyncSession, user_id: int) -> list[HistoryEntry]:
    raise NotImplementedError


async def append_entry(
    session: AsyncSession, user_id: int, document_id: int, verdict: str
) -> None:
    raise NotImplementedError
