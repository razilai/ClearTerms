"""Phase 2: forum business logic (posts, comments, likes).

Owner-only checks live here (delete post/comment, edit comment), as do the
phase-2 guardrails: posting rate limits and moderation hooks.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Post
from app.schemas.forum import PostCreate


async def create_post(session: AsyncSession, user_id: int, data: PostCreate) -> Post:
    raise NotImplementedError


async def list_posts(session: AsyncSession) -> list[Post]:
    raise NotImplementedError


async def get_post_detail(
    session: AsyncSession, post_id: int
) -> tuple[Post, list[Comment], int]:
    """Return (post, comments, like_count); raise if not found."""
    raise NotImplementedError


async def delete_post(session: AsyncSession, user_id: int, post_id: int) -> None:
    """Owner-only."""
    raise NotImplementedError


async def add_comment(
    session: AsyncSession, user_id: int, post_id: int, body: str
) -> Comment:
    raise NotImplementedError


async def edit_comment(
    session: AsyncSession, user_id: int, comment_id: int, body: str
) -> Comment:
    """Owner-only; sets edited_at."""
    raise NotImplementedError


async def delete_comment(session: AsyncSession, user_id: int, comment_id: int) -> None:
    """Owner-only."""
    raise NotImplementedError


async def toggle_like(
    session: AsyncSession, user_id: int, post_id: int
) -> tuple[int, bool]:
    """Return (like_count, liked-after-toggle)."""
    raise NotImplementedError


def check_rate_limit(user_id: int) -> None:
    """Phase-2 guardrail: raise when the user exceeds posting rate limits."""
    raise NotImplementedError
