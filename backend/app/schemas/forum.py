"""Phase 2: forum API contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings


class AttachmentOut(BaseModel):
    id: int
    media_type: str
    status: str
    mime: str
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    # None while status == "pending"
    display_url: str | None = None
    thumbnail_url: str | None = None


class PostCreate(BaseModel):
    # Length caps mirror the VARCHAR columns on app.models.forum.Post.
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    document_id: int | None = None
    is_anonymous: bool = False
    attachment_ids: list[int] = Field(
        default_factory=list, max_length=settings.max_attachments_per_item
    )


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)
    attachment_ids: list[int] = Field(
        default_factory=list, max_length=settings.max_attachments_per_item
    )


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1)


class CommentOut(BaseModel):
    id: int
    # Set when this comment belongs to the author of an anonymous post: their
    # replies inherit the post's anonymity, so author_email is None for every
    # viewer except them. Comments by anyone else are never anonymous.
    is_anonymous: bool = False
    author_email: str | None
    body: str
    created_at: datetime
    edited_at: datetime | None
    like_count: int = 0
    dislike_count: int = 0
    # This requester's own vote: -1, 0 or 1.
    my_vote: int = 0
    attachments: list[AttachmentOut] = Field(default_factory=list)


class PostOut(BaseModel):
    id: int
    # None on an anonymous post for every viewer except its author.
    author_email: str | None
    is_anonymous: bool = False
    title: str
    body: str
    like_count: int
    dislike_count: int = 0
    my_vote: int = 0
    created_at: datetime
    attachments: list[AttachmentOut] = Field(default_factory=list)


class PostDetail(PostOut):
    # First keyset page of comments (oldest first). comments_next_cursor is set
    # when more exist; fetch them from GET /forum/posts/{id}/comments?cursor=.
    comments: list[CommentOut]
    comments_next_cursor: str | None = None


class VoteRequest(BaseModel):
    value: Literal[-1, 1]


class VoteResponse(BaseModel):
    like_count: int
    dislike_count: int
    my_vote: int
