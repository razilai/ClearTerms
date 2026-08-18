"""Direct messaging: one message inside a conversation."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Message(Base):
    __tablename__ = "messages"
    # (conversation_id, created_at, id) covers one keyset page of a thread, in
    # either direction, with id as the tiebreak so the cursor is a total order.
    # It also serves plain conversation_id lookups (leading column), so no
    # separate single-column index is needed.
    __table_args__ = (
        Index(
            "ix_messages_conversation_created_id", "conversation_id", "created_at", "id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # ondelete=CASCADE: deleting a conversation drops its messages at the db
    # level, so the service does a single DELETE (mirrors Comment/Post).
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Text, like Post.body and Comment.body: the length cap is
    # settings.max_message_body_chars, enforced by the Pydantic schema.
    body: Mapped[str] = mapped_column(Text)
    # None until the recipient reads it; feeds unread counts / notifications.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
