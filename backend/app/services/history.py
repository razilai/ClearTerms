"""Per-user history of analyzed TOS documents.

Returns API schemas (not ORM rows) because HistoryEntryOut carries the document
url, which lives on Document, not HistoryEntry — a join the api layer is not
allowed to do (mirrors the forum service).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import documents as documents_repo
from app.db.repos import history as history_repo
from app.schemas.history import HistoryEntryOut


async def list_history(session: AsyncSession, user_id: int) -> list[HistoryEntryOut]:
    entries = await history_repo.list_for_user(session, user_id)
    urls = await documents_repo.get_urls(session, {e.document_id for e in entries})
    return [
        HistoryEntryOut(
            document_id=entry.document_id,
            url=urls.get(entry.document_id),
            verdict=entry.verdict,
            created_at=entry.created_at,
        )
        for entry in entries
    ]


async def append_entry(
    session: AsyncSession, user_id: int, document_id: int, verdict: str
) -> None:
    # Unused for now: the analysis pipeline appends via history_repo.append
    # directly. Kept so a future caller (e.g. a re-verdict flow) has a service seam.
    await history_repo.append(session, user_id, document_id, verdict)