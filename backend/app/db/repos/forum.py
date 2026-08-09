"""Phase 2: forum data access."""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Like, Post
from app.schemas.forum import PostCreate


async def create_post(session: AsyncSession, user_id: int, data: PostCreate) -> Post:
    post = Post(
        user_id=user_id,
        document_id=data.document_id,
        category=data.category,
        title=data.title,
        body=data.body,
    )
    session.add(post)
    # Flush, don't commit: the caller owns the transaction boundary. This
    # populates post.id and created_at (server default).
    await session.flush()
    return post


async def get_post(session: AsyncSession, post_id: int) -> Post | None:
    return await session.get(Post, post_id)


async def list_posts(
    session: AsyncSession,
    limit: int,
    cursor: tuple[datetime, int] | None = None,
) -> list[Post]:
    """One keyset page of posts, newest first. Fetches ``limit + 1`` so the
    caller can detect a further page. Uses the ``ix_posts_created_id`` index.
    """
    stmt = select(Post)
    if cursor is not None:
        stmt = stmt.where(tuple_(Post.created_at, Post.id) < cursor)
    stmt = stmt.order_by(Post.created_at.desc(), Post.id.desc()).limit(limit + 1)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_post(session: AsyncSession, post_id: int) -> None:
    # ondelete=CASCADE on comments.post_id / likes.post_id (see app.models.forum)
    # drops the children at the db level, so one DELETE is enough.
    await session.execute(delete(Post).where(Post.id == post_id))
    await session.flush()


async def create_comment(
    session: AsyncSession, post_id: int, user_id: int, body: str
) -> Comment:
    comment = Comment(post_id=post_id, user_id=user_id, body=body)
    session.add(comment)
    await session.flush()
    return comment


async def get_comment(session: AsyncSession, comment_id: int) -> Comment | None:
    return await session.get(Comment, comment_id)


async def list_comments(
    session: AsyncSession,
    post_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None = None,
) -> list[Comment]:
    """One keyset page of a post's comments, oldest first (chronological read).

    Ascending keyset: the next page is rows strictly *after* the cursor's
    ``(created_at, id)``. Fetches ``limit + 1``; uses ``ix_comments_post_created_id``.
    """
    stmt = select(Comment).where(Comment.post_id == post_id)
    if cursor is not None:
        stmt = stmt.where(tuple_(Comment.created_at, Comment.id) > cursor)
    stmt = stmt.order_by(Comment.created_at.asc(), Comment.id.asc()).limit(limit + 1)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_comment(
    session: AsyncSession, comment_id: int, body: str, edited_at: datetime
) -> Comment:
    comment = await session.get(Comment, comment_id)
    if comment is None:
        raise LookupError(f"comment {comment_id} not found")
    comment.body = body
    comment.edited_at = edited_at
    await session.flush()
    return comment


async def delete_comment(session: AsyncSession, comment_id: int) -> None:
    await session.execute(delete(Comment).where(Comment.id == comment_id))
    await session.flush()


async def get_like(session: AsyncSession, user_id: int, post_id: int) -> Like | None:
    result = await session.execute(
        select(Like).where(Like.user_id == user_id, Like.post_id == post_id)
    )
    return result.scalar_one_or_none()


async def add_like(session: AsyncSession, user_id: int, post_id: int) -> Like:
    like = Like(user_id=user_id, post_id=post_id)
    session.add(like)
    # The UniqueConstraint(user_id, post_id) surfaces a double-like as an
    # IntegrityError here rather than at the caller's commit.
    await session.flush()
    return like


async def remove_like(session: AsyncSession, user_id: int, post_id: int) -> None:
    await session.execute(
        delete(Like).where(Like.user_id == user_id, Like.post_id == post_id)
    )
    await session.flush()


async def count_likes(session: AsyncSession, post_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(Like).where(Like.post_id == post_id)
    )
    return result.scalar_one()


async def count_likes_by_post(
    session: AsyncSession, post_ids: Iterable[int]
) -> dict[int, int]:
    """Map post id -> like count; posts with no likes may be absent."""
    ids = list(post_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(Like.post_id, func.count())
        .where(Like.post_id.in_(ids))
        .group_by(Like.post_id)
    )
    return {post_id: count for post_id, count in result.all()}
