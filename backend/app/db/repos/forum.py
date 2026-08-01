"""Phase 2: forum data access."""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Like, Post
from app.schemas.forum import PostCreate


async def create_post(session: AsyncSession, user_id: int, data: PostCreate) -> Post:
    # TODO(db): INSERT and return the row with generated id/created_at.
    raise NotImplementedError


async def get_post(session: AsyncSession, post_id: int) -> Post | None:
    # TODO(db): SELECT by primary key.
    raise NotImplementedError


async def list_posts(session: AsyncSession) -> list[Post]:
    # TODO(db): SELECT ordered by created_at DESC.
    raise NotImplementedError


async def delete_post(session: AsyncSession, post_id: int) -> None:
    # TODO(db): DELETE; must cascade the post's comments and likes.
    raise NotImplementedError


async def create_comment(
    session: AsyncSession, post_id: int, user_id: int, body: str
) -> Comment:
    # TODO(db): INSERT and return the row with generated id/created_at.
    raise NotImplementedError


async def get_comment(session: AsyncSession, comment_id: int) -> Comment | None:
    # TODO(db): SELECT by primary key.
    raise NotImplementedError


async def list_comments(session: AsyncSession, post_id: int) -> list[Comment]:
    # TODO(db): SELECT WHERE post_id ordered by created_at ASC.
    raise NotImplementedError


async def update_comment(
    session: AsyncSession, comment_id: int, body: str, edited_at: datetime
) -> Comment:
    # TODO(db): UPDATE body + edited_at, return the row.
    raise NotImplementedError


async def delete_comment(session: AsyncSession, comment_id: int) -> None:
    # TODO(db): DELETE by primary key.
    raise NotImplementedError


async def get_like(session: AsyncSession, user_id: int, post_id: int) -> Like | None:
    # TODO(db): SELECT by the (user_id, post_id) unique pair.
    raise NotImplementedError


async def add_like(session: AsyncSession, user_id: int, post_id: int) -> Like:
    # TODO(db): INSERT; the UniqueConstraint(user_id, post_id) makes this
    # idempotent-safe under races.
    raise NotImplementedError


async def remove_like(session: AsyncSession, user_id: int, post_id: int) -> None:
    # TODO(db): DELETE by the (user_id, post_id) pair.
    raise NotImplementedError


async def count_likes(session: AsyncSession, post_id: int) -> int:
    # TODO(db): SELECT COUNT(*) WHERE post_id.
    raise NotImplementedError


async def count_likes_by_post(
    session: AsyncSession, post_ids: Iterable[int]
) -> dict[int, int]:
    """Map post id -> like count; posts with no likes may be absent."""
    # TODO(db): SELECT post_id, COUNT(*) GROUP BY post_id WHERE post_id IN (...).
    raise NotImplementedError
