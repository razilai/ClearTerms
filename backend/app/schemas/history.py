from datetime import datetime

from pydantic import BaseModel


class HistoryEntryOut(BaseModel):
    document_id: int
    url: str | None
    verdict: str
    created_at: datetime


class HistoryResponse(BaseModel):
    entries: list[HistoryEntryOut]
