"""Phase 2: forum business logic (posts, comments, likes, attachments).

Owner-only checks live here (delete post/comment, edit comment), as do the
phase-2 guardrails: posting rate limits and moderation hooks.

Services return API schemas (not ORM rows) because author_email requires
joining user emails — db work the api layer is not allowed to do.
"""

import uuid
from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import settings
from app.db.repos import attachments as attachments_repo
from app.db.repos import forum as forum_repo
from app.db.repos import users as users_repo
from app.models import Comment, Post, User
from app.models.attachment import Attachment
from app.schemas.forum import (
    AttachmentOut,
    CommentOut,
    LikeResponse,
    PostCreate,
    PostDetail,
    PostOut,
)
from app.schemas.pagination import Page, slice_page
from app.services import media as media_service
from app.services.exceptions import (
    NotFoundError,
    NotOwnerError,
    TooManyAttachmentsError,
)

# ---------------------------------------------------------------------------
# Attachment helpers
# ---------------------------------------------------------------------------


def _attachment_out(a: Attachment) -> AttachmentOut:
    return AttachmentOut(
        id=a.id,
        media_type=a.media_type,
        status=a.status,
        mime=a.mime,
        width=a.width,
        height=a.height,
        duration_seconds=a.duration_seconds,
        display_url=storage.presigned_get_url(a.display_key) if a.display_key else None,
        thumbnail_url=storage.presigned_get_url(a.thumbnail_key) if a.thumbnail_key else None,
    )


def _post_out(
    post: Post, author_email: str, like_count: int, attachments: list[Attachment]
) -> PostOut:
    return PostOut(
        id=post.id,
        author_email=author_email,
        title=post.title,
        body=post.body,
        category=post.category,
        like_count=like_count,
        created_at=post.created_at,
        attachments=[_attachment_out(a) for a in attachments],
    )


def _comment_out(comment: Comment, author_email: str, attachments: list[Attachment]) -> CommentOut:
    return CommentOut(
        id=comment.id,
        author_email=author_email,
        body=comment.body,
        created_at=comment.created_at,
        edited_at=comment.edited_at,
        attachments=[_attachment_out(a) for a in attachments],
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


async def _claim_attachments_for_post(
    session: AsyncSession, attachment_ids: list[int], user: User, post_id: int
) -> list[Attachment]:
    """Validate and link attachment_ids to a post; raise on any mismatch."""
    if not attachment_ids:
        return []
    rows = await attachments_repo.claim_for_post(session, attachment_ids, user.id, post_id)
    # Verify every requested id was claimed successfully
    claimed_ids = {a.id for a in rows if a.post_id == post_id}
    for aid in attachment_ids:
        if aid not in claimed_ids:
            raise NotFoundError("attachment")
    return rows


async def _claim_attachments_for_comment(
    session: AsyncSession, attachment_ids: list[int], user: User, comment_id: int
) -> list[Attachment]:
    """Validate and link attachment_ids to a comment; raise on any mismatch."""
    if not attachment_ids:
        return []
    rows = await attachments_repo.claim_for_comment(
        session, attachment_ids, user.id, comment_id
    )
    claimed_ids = {a.id for a in rows if a.comment_id == comment_id}
    for aid in attachment_ids:
        if aid not in claimed_ids:
            raise NotFoundError("attachment")
    return rows


# ---------------------------------------------------------------------------
# Attachment upload (pre-upload flow)
# ---------------------------------------------------------------------------


async def upload_attachment(
    session: AsyncSession,
    user: User,
    file: UploadFile,
    background_tasks,  # fastapi.BackgroundTasks
) -> AttachmentOut:
    """Validate, store original, create pending row, schedule processing."""
    data = await file.read()
    media_type, real_mime = await media_service.validate_upload(file, data)

    key = f"attachments/{uuid.uuid4()}/original"
    await storage.put_object(key, data, real_mime)

    attachment = await attachments_repo.create(
        session,
        user_id=user.id,
        media_type=media_type,
        mime=real_mime,
        size_bytes=len(data),
        original_key=key,
    )

    background_tasks.add_task(media_service.process_attachment, attachment.id)
    return _attachment_out(attachment)


async def get_attachment(session: AsyncSession, attachment_id: int) -> AttachmentOut:
    attachment = await attachments_repo.get(session, attachment_id)
    if attachment is None:
        raise NotFoundError("attachment")
    return _attachment_out(attachment)


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------


async def create_post(session: AsyncSession, user: User, data: PostCreate) -> PostOut:
    if len(data.attachment_ids) > settings.max_attachments_per_item:
        raise TooManyAttachmentsError()
    post = await forum_repo.create_post(session, user.id, data)
    attachments = await _claim_attachments_for_post(
        session, data.attachment_ids, user, post.id
    )
    return _post_out(post, author_email=user.email, like_count=0, attachments=attachments)


async def list_posts(
    session: AsyncSession,
    limit: int,
    cursor: tuple[datetime, int] | None,
) -> Page[PostOut]:
    posts = await forum_repo.list_posts(session, limit, cursor)
    posts, next_cursor = slice_page(posts, limit, lambda p: (p.created_at, p.id))
    emails = await users_repo.get_emails(session, {p.user_id for p in posts})
    counts = await forum_repo.count_likes_by_post(session, [p.id for p in posts])
    post_attachments = await attachments_repo.list_for_posts(
        session, [p.id for p in posts]
    )
    items = [
        _post_out(p, emails[p.user_id], counts.get(p.id, 0), post_attachments.get(p.id, []))
        for p in posts
    ]
    return Page(items=items, next_cursor=next_cursor)


_COMMENTS_PREVIEW_LIMIT = 20


async def get_post_detail(session: AsyncSession, post_id: int) -> PostDetail:
    post = await _require_post(session, post_id)
    page = await list_post_comments(session, post_id, _COMMENTS_PREVIEW_LIMIT, None)
    like_count = await forum_repo.count_likes(session, post_id)
    author_email = (await users_repo.get_emails(session, {post.user_id}))[post.user_id]
    post_attachments = (await attachments_repo.list_for_posts(session, [post_id])).get(
        post_id, []
    )
    return PostDetail(
        **_post_out(post, author_email, like_count, post_attachments).model_dump(),
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
    comment_attachments = await attachments_repo.list_for_comments(
        session, [c.id for c in comments]
    )
    items = [
        _comment_out(c, emails[c.user_id], comment_attachments.get(c.id, []))
        for c in comments
    ]
    return Page(items=items, next_cursor=next_cursor)


async def delete_post(session: AsyncSession, user_id: int, post_id: int) -> None:
    """Owner-only. Cleans up S3 objects before cascade removes the rows."""
    post = await _require_post(session, post_id)
    if post.user_id != user_id:
        raise NotOwnerError
    # Delete objects first — once the row is gone we can't recover the keys
    keys = await attachments_repo.keys_for_post(session, post_id)
    await storage.delete_objects(keys)
    await forum_repo.delete_post(session, post_id)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


async def add_comment(
    session: AsyncSession, user: User, post_id: int, body: str,
    attachment_ids: list[int] | None = None,
) -> CommentOut:
    if attachment_ids and len(attachment_ids) > settings.max_attachments_per_item:
        raise TooManyAttachmentsError()
    await _require_post(session, post_id)
    comment = await forum_repo.create_comment(session, post_id, user.id, body)
    attachments = await _claim_attachments_for_comment(
        session, attachment_ids or [], user, comment.id
    )
    return _comment_out(comment, author_email=user.email, attachments=attachments)


async def edit_comment(
    session: AsyncSession, user: User, comment_id: int, body: str
) -> CommentOut:
    """Owner-only; sets edited_at. Attachments are not changed on edit."""
    await _require_owned_comment(session, user.id, comment_id)
    updated = await forum_repo.update_comment(
        session, comment_id, body, edited_at=datetime.now(UTC)
    )
    comment_attachments = (
        await attachments_repo.list_for_comments(session, [comment_id])
    ).get(comment_id, [])
    return _comment_out(updated, author_email=user.email, attachments=comment_attachments)


async def delete_comment(session: AsyncSession, user_id: int, comment_id: int) -> None:
    """Owner-only. Cleans up S3 objects before cascade."""
    await _require_owned_comment(session, user_id, comment_id)
    keys = await attachments_repo.keys_for_comment(session, comment_id)
    await storage.delete_objects(keys)
    await forum_repo.delete_comment(session, comment_id)


# ---------------------------------------------------------------------------
# Likes
# ---------------------------------------------------------------------------


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
