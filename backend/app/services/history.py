"""Per-user history of analyzed TOS documents.

Returns API schemas (not ORM rows) because HistoryEntryOut carries the document
url, which lives on Document, not HistoryEntry — a join the api layer is not
allowed to do (mirrors the forum service).

Verdicts are recomputed here rather than read off HistoryEntry.verdict: that
column is a snapshot from analyze time, and preferences are a checklist the
user can change afterwards. Recomputing keeps the list agreeing with the detail
view, which hides unchecked categories.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.repos import documents as documents_repo
from app.db.repos import history as history_repo
from app.db.repos import preferences as preferences_repo
from app.schemas.history import HistoryEntryOut
from app.schemas.pagination import Page, slice_page
from app.services.preferences import compute_verdict


async def list_history(
    session: AsyncSession,
    user_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None,
) -> Page[HistoryEntryOut]:
    rows = await history_repo.list_for_user(session, user_id, limit, cursor)
    rows, next_cursor = slice_page(rows, limit, lambda e: (e.created_at, e.id))
    document_ids = {e.document_id for e in rows}
    urls = await documents_repo.get_urls(session, document_ids)
    scores = await documents_repo.get_analyses_for_documents(
        session, document_ids, settings.model_version
    )
    prefs = await preferences_repo.get_for_user(session, user_id)
    items = [
        HistoryEntryOut(
            document_id=entry.document_id,
            url=urls.get(entry.document_id),
            # No cached scores at the current model_version (the model was
            # bumped since this entry was written) means there is nothing to
            # recompute from, and an empty score list would fabricate a
            # thumbs-up. Fall back to the snapshot instead.
            verdict=(
                compute_verdict(scores[entry.document_id], prefs)
                if entry.document_id in scores
                else entry.verdict
            ),
            created_at=entry.created_at,
        )
        for entry in rows
    ]
    return Page(items=items, next_cursor=next_cursor)