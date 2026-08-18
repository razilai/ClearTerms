"""Direct messaging: a one-to-one conversation between two users."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # Participants are stored canonically, smaller user id first, so a pair
        # has one representation. Without this the unique constraint below is
        # toothless: (3, 5) and (5, 3) would be two rows for the same two people.
        # It also rules out a self-conversation, since equality fails the check.
        CheckConstraint("user_a_id < user_b_id", name="ck_conversations_user_order"),
        UniqueConstraint("user_a_id", "user_b_id"),
        # The inbox is "my conversations, most recent first". Either column can
        # be "me", so each participant column leads its own covering index with
        # last_message_at as the sort key.
        Index("ix_conversations_user_a_last_message", "user_a_id", "last_message_at"),
        Index("ix_conversations_user_b_last_message", "user_b_id", "last_message_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_a_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    user_b_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # Denormalized sort key for the inbox: ordering by a join onto the newest
    # message would scan every thread. The service bumps it on each send.
    # Defaults to creation time so a thread with no messages still sorts sanely.
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
