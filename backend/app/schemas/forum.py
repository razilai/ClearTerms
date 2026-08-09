"""Phase 2: forum API contracts."""

from datetime import datetime

from pydantic import BaseModel, Field


class PostCreate(BaseModel):
    # Length caps mirror the VARCHAR columns on app.models.forum.Post.
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    document_id: int | None = None
    category: str | None = Field(default=None, max_length=64)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1)


class CommentOut(BaseModel):
    id: int
    author_email: str
    body: str
    created_at: datetime
    edited_at: datetime | None


class PostOut(BaseModel):
    id: int
    author_email: str
    title: str
    body: str
    category: str | None
    like_count: int
    created_at: datetime


class PostDetail(PostOut):
    # First keyset page of comments (oldest first). comments_next_cursor is set
    # when more exist; fetch them from GET /forum/posts/{id}/comments?cursor=.
    comments: list[CommentOut]
    comments_next_cursor: str | None = None


class LikeResponse(BaseModel):
    like_count: int
    liked: bool
