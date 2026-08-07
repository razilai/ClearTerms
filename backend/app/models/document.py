from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    text_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    url: Mapped[str | None] = mapped_column(String(2048))
    normalized_text: Mapped[str] = mapped_column(Text)
    # What the agent reads. normalized_text is casefolded with all whitespace
    # collapsed, which is right for hashing and fatal for chunking: no line
    # breaks means no section headings, so every document would fall back to
    # blind windows and clauses would be cut in half.
    original_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
