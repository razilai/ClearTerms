"""Phase 2: forum API contracts."""

from datetime import datetime

from pydantic import BaseModel


class PostCreate(BaseModel):
    title: str
    body: str
    document_id: int | None = None
    category: str | None = None


class CommentCreate(BaseModel):
    body: str


class CommentUpdate(BaseModel):
    body: str


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
    comments: list[CommentOut]


class LikeResponse(BaseModel):
    like_count: int
    liked: bool
