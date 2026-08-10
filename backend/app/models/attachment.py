"""Attachment: a media file (image or video) linked to a post or comment."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        # At most one of post_id / comment_id is set; both null = unlinked (just
        # uploaded, not yet claimed by a post/comment create).
        CheckConstraint(
            "NOT (post_id IS NOT NULL AND comment_id IS NOT NULL)",
            name="ck_attachments_single_owner",
        ),
        Index("ix_attachments_post_id", "post_id"),
        Index("ix_attachments_comment_id", "comment_id"),
        Index("ix_attachments_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # ondelete=CASCADE: deleting a post/comment drops its attachments at db level.
    # Object-store cleanup must happen BEFORE the db delete (service responsibility).
    post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE")
    )
    comment_id: Mapped[int | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE")
    )

    media_type: Mapped[str] = mapped_column(String(8))   # "image" | "video"
    status: Mapped[str] = mapped_column(String(16))      # "pending" | "ready" | "failed"
    mime: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]

    # Object-storage keys; None until processing sets them
    original_key: Mapped[str] = mapped_column(String(256))
    display_key: Mapped[str | None] = mapped_column(String(256))
    thumbnail_key: Mapped[str | None] = mapped_column(String(256))

    # Dimensions / duration; None until ready
    width: Mapped[int | None]
    height: Mapped[int | None]
    duration_seconds: Mapped[float | None]

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
