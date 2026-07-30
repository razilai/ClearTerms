from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (UniqueConstraint("document_id", "category", "model_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    category: Mapped[str] = mapped_column(String(64))
    score: Mapped[int]
    explanation: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str] = mapped_column(String(64))
