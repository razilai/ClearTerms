"""Phase 2: forum data access."""

from collections.abc import Iterable
from datetime import datetime
from typing import NamedTuple, TypeVar

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, CommentVote, Post, PostVote
from app.schemas.forum import PostCreate

# ---------------------------------------------------------------------------
# Post operations
# ---------------------------------------------------------------------------

async def create_post(session: AsyncSession, user_id: int, data: PostCreate) -> Post:
    post = Post(
        user_id=user_id,
        document_id=data.document_id,
        title=data.title,
        body=data.body,
        is_anonymous=data.is_anonymous,
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
    author_id: int | None = None,
) -> list[Post]:
    """One keyset page of posts, newest first. Fetches ``limit + 1`` so the
    caller can detect a further page. Uses the ``ix_posts_created_id`` index.

    ``author_id`` narrows the page to one author's posts (the personal area);
    None is the whole forum.
    """
    stmt = select(Post)
    if author_id is not None:
        stmt = stmt.where(Post.user_id == author_id)
    if cursor is not None:
        stmt = stmt.where(tuple_(Post.created_at, Post.id) < cursor)
    stmt = stmt.order_by(Post.created_at.desc(), Post.id.desc()).limit(limit + 1)
    result = await session.execute(stmt)
    return list(result.scalars().all())


class AuthorTotals(NamedTuple):
    post_count: int
    likes: int
    dislikes: int


async def author_totals(session: AsyncSession, user_id: int) -> AuthorTotals:
    """How many posts this user wrote and how they were voted on, in aggregate.

    Two grouped queries rather than a page-and-sum: the personal-area header must
    cover every post the user ever wrote, not just the page on screen.
    """
    posts = await session.execute(
        select(func.count()).select_from(Post).where(Post.user_id == user_id)
    )
    votes = await session.execute(
        select(PostVote.value, func.count())
        .join(Post, Post.id == PostVote.target_id)
        .where(Post.user_id == user_id)
        .group_by(PostVote.value)
    )
    likes = dislikes = 0
    for value, count in votes.all():
        if value > 0:
            likes = count
        else:
            dislikes = count
    return AuthorTotals(posts.scalar_one(), likes, dislikes)


async def delete_post(session: AsyncSession, post_id: int) -> None:
    # ondelete=CASCADE on comments.post_id / post_votes.target_id (see
    # app.models.forum) drops the children at the db level, so one DELETE is enough
    await session.execute(delete(Post).where(Post.id == post_id))
    await session.flush()



# ---------------------------------------------------------------------------
# Comment operations
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Vote operations
# ---------------------------------------------------------------------------

VoteT = TypeVar("VoteT", PostVote, CommentVote)


class VoteCounts(NamedTuple):
    likes: int
    dislikes: int


async def get_vote(session: AsyncSession, model: type[VoteT], user_id: int, target_id: int) -> VoteT | None:
    result = await session.execute(
        select(model).where(model.user_id == user_id, model.target_id == target_id)
    )
    return result.scalar_one_or_none()


async def set_vote(session: AsyncSession, model: type[VoteT], user_id: int, target_id: int, value: int) -> None:
    """Insert the vote, or update it in place if this user already voted.

    The UniqueConstraint(user_id, target_id) makes a blind insert an
    IntegrityError, so an existing row is updated rather than added.
    """
    existing = await get_vote(session, model, user_id, target_id)
    if existing is None:
        session.add(model(user_id=user_id, target_id=target_id, value=value))
    else:
        existing.value = value
    await session.flush()


async def remove_vote(
    session: AsyncSession, model: type[VoteT], user_id: int, target_id: int
) -> None:
    await session.execute(
        delete(model).where(model.user_id == user_id, model.target_id == target_id)
    )
    await session.flush()


async def count_votes(session: AsyncSession, model: type[VoteT], target_ids: Iterable[int]) -> dict[int, VoteCounts]:
    """Map target id -> (likes, dislikes). Targets with no votes are absent

    One grouped query for the whole page — counting per target in a loop would
    be an N+1 on every post list and every page of comments.
    """
    ids = list(target_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(model.target_id, model.value, func.count())
        .where(model.target_id.in_(ids))
        .group_by(model.target_id, model.value)
    )
    counts: dict[int, VoteCounts] = {}
    for target_id, value, count in result.all():
        current = counts.get(target_id, VoteCounts(0, 0))
        counts[target_id] = (
            VoteCounts(count, current.dislikes)
            if value > 0
            else VoteCounts(current.likes, count)
        )
    return counts


async def get_my_votes(session: AsyncSession, model: type[VoteT], user_id: int, target_ids: Iterable[int]) -> dict[int, int]:
    """Map target id -> this user's vote value. Unvoted targets are absent."""
    ids = list(target_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(model.target_id, model.value).where(
            model.user_id == user_id, model.target_id.in_(ids)
        )
    )
    return {target_id: value for target_id, value in result.all()}