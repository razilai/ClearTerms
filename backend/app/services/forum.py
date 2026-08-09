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
from app.schemas.pagination import Page, slice_page
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


async def list_posts(
    session: AsyncSession,
    limit: int,
    cursor: tuple[datetime, int] | None,
) -> Page[PostOut]:
    posts = await forum_repo.list_posts(session, limit, cursor)
    posts, next_cursor = slice_page(posts, limit, lambda p: (p.created_at, p.id))
    emails = await users_repo.get_emails(session, {p.user_id for p in posts})
    counts = await forum_repo.count_likes_by_post(session, [p.id for p in posts])
    items = [_post_out(p, emails[p.user_id], counts.get(p.id, 0)) for p in posts]
    return Page(items=items, next_cursor=next_cursor)


# Comments embedded in the post detail default to this first-page size; further
# pages come from list_post_comments with an explicit limit.
_COMMENTS_PREVIEW_LIMIT = 20


async def get_post_detail(session: AsyncSession, post_id: int) -> PostDetail:
    post = await _require_post(session, post_id)
    page = await list_post_comments(session, post_id, _COMMENTS_PREVIEW_LIMIT, None)
    like_count = await forum_repo.count_likes(session, post_id)
    author_email = (await users_repo.get_emails(session, {post.user_id}))[post.user_id]
    return PostDetail(
        **_post_out(post, author_email, like_count).model_dump(),
        comments=page.items,
        comments_next_cursor=page.next_cursor,
    )


async def list_post_comments(
    session: AsyncSession,
    post_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None,
) -> Page[CommentOut]:
    """One keyset page of a post's comments (oldest first). Raises if the post
    is gone so a stale link 404s rather than returning an empty page.
    """
    await _require_post(session, post_id)
    comments = await forum_repo.list_comments(session, post_id, limit, cursor)
    comments, next_cursor = slice_page(
        comments, limit, lambda c: (c.created_at, c.id)
    )
    emails = await users_repo.get_emails(session, {c.user_id for c in comments})
    items = [_comment_out(c, emails[c.user_id]) for c in comments]
    return Page(items=items, next_cursor=next_cursor)


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
