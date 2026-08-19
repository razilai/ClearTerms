"""An event another user caused that the recipient should be told about."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        # The dedupe key. What collapses is decided entirely by what each kind
        # stores in target_id: a vote points at the thing voted on (so one
        # actor voting twice is one row), while a DM points at the message and
        # a comment at the comment (so each one notifies separately). Every
        # column here is non-null, which keeps Postgres' NULL-distinct rule out
        # of the picture.
        UniqueConstraint(
            "recipient_id",
            "actor_id",
            "kind",
            "target_id",
            name="uq_notifications_event",
        ),
        # Serves the newest-first keyset page and, on its leading column, the
        # unread count.
        Index(
            "ix_notifications_recipient_created_id",
            "recipient_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # 'dm' | 'post_comment' | 'post_vote' | 'comment_vote'. Kept a plain string
    # rather than a db enum so adding a kind is a code change, not a migration.
    kind: Mapped[str] = mapped_column(String(32))
    # Untyped on purpose: its referent varies by kind, so it cannot be a FK.
    target_id: Mapped[int] = mapped_column(Integer)
    # +1 / -1 for the vote kinds, so the toast can say liked vs disliked.
    value: Mapped[int | None] = mapped_column(Integer)
    # These three exist for ON DELETE CASCADE, not for reads: target_id cannot
    # be a foreign key, so without them deleting a post or comment would strand
    # notifications pointing at it. Reads use post_id and conversation_id for
    # navigation; comment_id is carried only so the cascade can find the row.
    post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE")
    )
    comment_id: Mapped[int | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE")
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # None until the recipient acknowledges it; drives the bell badge.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
