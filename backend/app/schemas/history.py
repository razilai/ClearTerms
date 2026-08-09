from datetime import datetime

from pydantic import BaseModel

# The list response is Page[HistoryEntryOut] (app.schemas.pagination) — items +
# next_cursor — so the earlier HistoryResponse wrapper is gone.


class HistoryEntryOut(BaseModel):
    document_id: int
    url: str | None
    verdict: str
    created_at: datetime
