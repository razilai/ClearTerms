"""Phase 2: forum entities (Post, Comment, Like)."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Post(Base):
    __tablename__ = "posts"
    # (created_at, id) desc covers list_posts' keyset page: newest first, id as
    # the tiebreak so the cursor is a total order (two posts can share a second).
    __table_args__ = (Index("ix_posts_created_id", "created_at", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id"), index=True
    )
    category: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Comment(Base):
    __tablename__ = "comments"
    # (post_id, created_at, id) covers list_comments' keyset page within a post;
    # it also serves plain post_id lookups (leading column), so no separate
    # single-column index on post_id is needed.
    __table_args__ = (Index("ix_comments_post_created_id", "post_id", "created_at", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # ondelete=CASCADE: deleting a post drops its comments at the db level, so
    # the service does a single DELETE on the post (mirrors Finding/Analysis).
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Like(Base):
    __tablename__ = "likes"
    __table_args__ = (UniqueConstraint("user_id", "post_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # ondelete=CASCADE: deleting a post drops its likes at the db level.
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
