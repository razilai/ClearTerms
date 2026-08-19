"""Phase 2: forum data access."""

from collections.abc import Iterable
from datetime import datetime
from typing import NamedTuple, TypeVar

from sqlalchemy import Row, delete, func, select, tuple_
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


async def get_post_titles(
    session: AsyncSession, post_ids: Iterable[int]
) -> dict[int, str]:
    """Map post id -> title, for callers that render a post reference without
    loading the whole row (the notification feed). One query for the page,
    rather than an N+1."""
    ids = list(post_ids)
    if not ids:
        return {}
    result = await session.execute(select(Post.id, Post.title).where(Post.id.in_(ids)))
    return {post_id: title for post_id, title in result.all()}


class AuthorTotals(NamedTuple):
    post_count: int
    likes: int
    dislikes: int
    comment_count: int
    comment_likes: int
    comment_dislikes: int


def _split_votes(rows: Iterable[Row[tuple[int, int]]]) -> tuple[int, int]:
    """Fold a (value, count) group-by into (likes, dislikes)."""
    likes = dislikes = 0
    for value, count in rows:
        if value > 0:
            likes = count
        else:
            dislikes = count
    return likes, dislikes


async def author_totals(session: AsyncSession, user_id: int) -> AuthorTotals:
    """What this user wrote — posts and comments — and how it was voted on.

    Grouped queries rather than a page-and-sum: the personal-area header must
    cover everything the user ever wrote, not just the page on screen. Posts and
    comments stay separate tallies; the header shows one box for each.
    """
    posts = await session.execute(
        select(func.count()).select_from(Post).where(Post.user_id == user_id)
    )
    post_votes = await session.execute(
        select(PostVote.value, func.count())
        .join(Post, Post.id == PostVote.target_id)
        .where(Post.user_id == user_id)
        .group_by(PostVote.value)
    )
    comments = await session.execute(
        select(func.count()).select_from(Comment).where(Comment.user_id == user_id)
    )
    comment_votes = await session.execute(
        select(CommentVote.value, func.count())
        .join(Comment, Comment.id == CommentVote.target_id)
        .where(Comment.user_id == user_id)
        .group_by(CommentVote.value)
    )
    likes, dislikes = _split_votes(post_votes.all())
    comment_likes, comment_dislikes = _split_votes(comment_votes.all())
    return AuthorTotals(
        posts.scalar_one(),
        likes,
        dislikes,
        comments.scalar_one(),
        comment_likes,
        comment_dislikes,
    )


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


async def list_voters(
    session: AsyncSession,
    model: type[VoteT],
    target_id: int,
    limit: int,
    value: int | None = None,
    cursor: int | None = None,
) -> list[VoteT]:
    """One keyset page of the votes cast on a target, newest first.

    Paged by ``id`` rather than ``(created_at, id)``: vote rows carry no
    timestamp, and the primary key is monotonic, so it is already a total
    order. ``value`` narrows to likes (1) or dislikes (-1). Fetches
    ``limit + 1`` so the caller can detect a further page; the ``target_id``
    index serves the lookup.
    """
    stmt = select(model).where(model.target_id == target_id)
    if value is not None:
        stmt = stmt.where(model.value == value)
    if cursor is not None:
        stmt = stmt.where(model.id < cursor)
    stmt = stmt.order_by(model.id.desc()).limit(limit + 1)
    result = await session.execute(stmt)
    return list(result.scalars().all())


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