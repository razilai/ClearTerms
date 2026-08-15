from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Preference(Base):
    __tablename__ = "preferences"
    __table_args__ = (UniqueConstraint("user_id", "category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(64))
    # Binary: an unchecked category is dropped from the report and can never
    # produce a thumbs-down. Rows only exist for categories the user has saved;
    # anything absent falls back to DEFAULT_ENABLED in the preferences service.
    enabled: Mapped[bool]
