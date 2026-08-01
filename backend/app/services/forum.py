"""Phase 2: forum business logic (posts, comments, likes).

Owner-only checks live here (delete post/comment, edit comment), as do the
phase-2 guardrails: posting rate limits and moderation hooks.

Services return API schemas (not ORM rows) because author_email requires
joining user emails — db work the api layer is not allowed to do.
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import forum as forum_repo
from app.db.repos import users as users_repo
from app.models import Comment, Post, User
from app.schemas.forum import (
    CommentOut,
    LikeResponse,
    PostCreate,
    PostDetail,
    PostOut,
)
from app.services.exceptions import NotFoundError, NotOwnerError


def _post_out(post: Post, author_email: str, like_count: int) -> PostOut:
    return PostOut(
        id=post.id,
        author_email=author_email,
        title=post.title,
        body=post.body,
        category=post.category,
        like_count=like_count,
        created_at=post.created_at,
    )


def _comment_out(comment: Comment, author_email: str) -> CommentOut:
    return CommentOut(
        id=comment.id,
        author_email=author_email,
        body=comment.body,
        created_at=comment.created_at,
        edited_at=comment.edited_at,
    )


async def _require_post(session: AsyncSession, post_id: int) -> Post:
    post = await forum_repo.get_post(session, post_id)
    if post is None:
        raise NotFoundError("post")
    return post


async def _require_owned_comment(
    session: AsyncSession, user_id: int, comment_id: int
) -> Comment:
    comment = await forum_repo.get_comment(session, comment_id)
    if comment is None:
        raise NotFoundError("comment")
    if comment.user_id != user_id:
        raise NotOwnerError
    return comment


async def create_post(session: AsyncSession, user: User, data: PostCreate) -> PostOut:
    post = await forum_repo.create_post(session, user.id, data)
    return _post_out(post, author_email=user.email, like_count=0)


async def list_posts(session: AsyncSession) -> list[PostOut]:
    posts = await forum_repo.list_posts(session)
    emails = await users_repo.get_emails(session, {p.user_id for p in posts})
    counts = await forum_repo.count_likes_by_post(session, [p.id for p in posts])
    return [_post_out(p, emails[p.user_id], counts.get(p.id, 0)) for p in posts]


async def get_post_detail(session: AsyncSession, post_id: int) -> PostDetail:
    post = await _require_post(session, post_id)
    comments = await forum_repo.list_comments(session, post_id)
    like_count = await forum_repo.count_likes(session, post_id)
    emails = await users_repo.get_emails(
        session, {post.user_id, *(c.user_id for c in comments)}
    )
    return PostDetail(
        **_post_out(post, emails[post.user_id], like_count).model_dump(),
        comments=[_comment_out(c, emails[c.user_id]) for c in comments],
    )


async def delete_post(session: AsyncSession, user_id: int, post_id: int) -> None:
    """Owner-only."""
    post = await _require_post(session, post_id)
    if post.user_id != user_id:
        raise NotOwnerError
    await forum_repo.delete_post(session, post_id)


async def add_comment(
    session: AsyncSession, user: User, post_id: int, body: str
) -> CommentOut:
    await _require_post(session, post_id)
    comment = await forum_repo.create_comment(session, post_id, user.id, body)
    return _comment_out(comment, author_email=user.email)


async def edit_comment(
    session: AsyncSession, user: User, comment_id: int, body: str
) -> CommentOut:
    """Owner-only; sets edited_at."""
    await _require_owned_comment(session, user.id, comment_id)
    updated = await forum_repo.update_comment(
        session, comment_id, body, edited_at=datetime.now(UTC)
    )
    return _comment_out(updated, author_email=user.email)


async def delete_comment(session: AsyncSession, user_id: int, comment_id: int) -> None:
    """Owner-only."""
    await _require_owned_comment(session, user_id, comment_id)
    await forum_repo.delete_comment(session, comment_id)


async def toggle_like(
    session: AsyncSession, user_id: int, post_id: int
) -> LikeResponse:
    await _require_post(session, post_id)
    liked = await forum_repo.get_like(session, user_id, post_id) is None
    if liked:
        await forum_repo.add_like(session, user_id, post_id)
    else:
        await forum_repo.remove_like(session, user_id, post_id)
    like_count = await forum_repo.count_likes(session, post_id)
    return LikeResponse(like_count=like_count, liked=liked)


def check_rate_limit(user_id: int) -> None:
    """Phase-2 guardrail: raise when the user exceeds posting rate limits."""
    raise NotImplementedError
