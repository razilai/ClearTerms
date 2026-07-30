"""Phase 2: forum data access."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Like, Post
from app.schemas.forum import PostCreate


async def create_post(session: AsyncSession, user_id: int, data: PostCreate) -> Post:
    raise NotImplementedError


async def get_post(session: AsyncSession, post_id: int) -> Post | None:
    raise NotImplementedError


async def list_posts(session: AsyncSession) -> list[Post]:
    raise NotImplementedError


async def delete_post(session: AsyncSession, post_id: int) -> None:
    raise NotImplementedError


async def create_comment(
    session: AsyncSession, post_id: int, user_id: int, body: str
) -> Comment:
    raise NotImplementedError


async def get_comment(session: AsyncSession, comment_id: int) -> Comment | None:
    raise NotImplementedError


async def update_comment(session: AsyncSession, comment_id: int, body: str) -> Comment:
    raise NotImplementedError


async def delete_comment(session: AsyncSession, comment_id: int) -> None:
    raise NotImplementedError


async def add_like(session: AsyncSession, user_id: int, post_id: int) -> Like:
    raise NotImplementedError


async def remove_like(session: AsyncSession, user_id: int, post_id: int) -> None:
    raise NotImplementedError


async def count_likes(session: AsyncSession, post_id: int) -> int:
    raise NotImplementedError
