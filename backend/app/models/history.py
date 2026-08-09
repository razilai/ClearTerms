from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class HistoryEntry(Base):
    __tablename__ = "history_entries"
    # user_id first (the filter), created_at second (the sort) — covers
    # list_for_user's "where user_id = ? order by created_at desc".
    __table_args__ = (Index("ix_history_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    verdict: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
