"""Phase 2: forum business logic (posts, comments, likes, attachments).

Owner-only checks live here (delete post/comment, edit comment), as do the
phase-2 guardrails: posting rate limits and moderation hooks.

Services return API schemas (not ORM rows) because author_email requires
joining user emails — db work the api layer is not allowed to do.
"""

import uuid
from datetime import UTC, datetime
from typing import NamedTuple

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import settings
from app.db.repos import attachments as attachments_repo
from app.db.repos import forum as forum_repo
from app.db.repos import users as users_repo
from app.models import Comment, CommentVote, Post, PostVote, User
from app.models.attachment import Attachment
from app.schemas.forum import (
    AttachmentOut,
    CommentOut,
    MyVoteTotals,
    PostCreate,
    PostDetail,
    PostOut,
    VoteResponse,
    VoterOut,
)
from app.schemas.notifications import NotificationKind
from app.schemas.pagination import Page, slice_page, slice_page_by_id
from app.services import media as media_service
from app.services import notifications as notifications_service
from app.services.exceptions import (
    NotFoundError,
    NotOwnerError,
    TooManyAttachmentsError,
)

# ---------------------------------------------------------------------------
# Attachment helpers
# ---------------------------------------------------------------------------


# Shared with the messages service — attachments hang off posts, comments and
# messages alike, so the mapper lives in app.services.media.
_attachment_out = media_service.attachment_out


class VoteState(NamedTuple):
    """Vote summary for one target (post or comment). As seen by user"""
    likes: int
    dislikes: int
    my_vote: int  # -1, 0 or 1

_NO_VOTES = VoteState(likes=0, dislikes=0, my_vote=0)


async def _vote_state(session: AsyncSession,model: type[forum_repo.VoteT],
    user_id: int, target_ids: list[int],) -> dict[int, VoteState]:
    """Counts plus the viewer's own vote, for a whole page in two queries."""
    counts = await forum_repo.count_votes(session, model, target_ids)
    mine = await forum_repo.get_my_votes(session, model, user_id, target_ids)
    return {
        target_id: VoteState(
            counts.get(target_id, forum_repo.VoteCounts(0, 0)).likes,
            counts.get(target_id, forum_repo.VoteCounts(0, 0)).dislikes,
            mine.get(target_id, 0),
        )
        for target_id in target_ids
    }



def _post_out(
    post: Post,
    author_email: str,
    votes: VoteState,
    attachments: list[Attachment],
    viewer_id: int,
) -> PostOut:
    # Single choke point for anonymity: an anonymous post withholds the author's
    # email from everyone but the author, who still needs it for the owner-only
    # UI (the server enforces ownership from post.user_id regardless).
    visible_email = (
        author_email if not post.is_anonymous or post.user_id == viewer_id else None
    )
    return PostOut(
        id=post.id,
        author_email=visible_email,
        is_anonymous=post.is_anonymous,
        title=post.title,
        body=post.body,
        like_count=votes.likes,
        dislike_count=votes.dislikes,
        my_vote=votes.my_vote,
        created_at=post.created_at,
        attachments=[_attachment_out(a) for a in attachments],
    )


def _comment_out(
    comment: Comment,
    author_email: str,
    votes: VoteState,
    attachments: list[Attachment],
    post: Post,
    viewer_id: int,
) -> CommentOut:
    # A comment is anonymous only by inheritance: the author of an anonymous post
    # replying under it. Without this, replying by name deanonymises the post.
    is_anonymous = post.is_anonymous and comment.user_id == post.user_id
    visible_email = (
        None if is_anonymous and comment.user_id != viewer_id else author_email
    )
    return CommentOut(
        id=comment.id,
        is_anonymous=is_anonymous,
        author_email=visible_email,
        body=comment.body,
        created_at=comment.created_at,
        edited_at=comment.edited_at,
        like_count=votes.likes,
        dislike_count=votes.dislikes,
        my_vote=votes.my_vote,
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

    # Commit before scheduling: the background worker opens its own session on a
    # different connection, so the row must be durable when it runs. FastAPI runs
    # BackgroundTasks before the request session's own commit, so without this the
    # worker reads None and bails, leaving the attachment stuck "pending" forever.
    await session.commit()

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
    return _post_out(
        post,
        author_email=user.email,
        votes=_NO_VOTES,
        attachments=attachments,
        viewer_id=user.id,
    )


async def list_posts(
    session: AsyncSession,
    user_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None,
    author_id: int | None = None,
) -> Page[PostOut]:
    """One page of the forum, or of ``author_id``'s own posts when given."""
    posts = await forum_repo.list_posts(session, limit, cursor, author_id=author_id)
    posts, next_cursor = slice_page(posts, limit, lambda p: (p.created_at, p.id))
    emails = await users_repo.get_emails(session, {p.user_id for p in posts})
    votes = await _vote_state(session, PostVote, user_id, [p.id for p in posts])
    post_attachments = await attachments_repo.list_for_posts(
        session, [p.id for p in posts]
    )
    items = [
        _post_out(
            p,
            emails[p.user_id],
            votes.get(p.id, _NO_VOTES),
            post_attachments.get(p.id, []),
            viewer_id=user_id,
        )
        for p in posts
    ]
    return Page(items=items, next_cursor=next_cursor)


async def my_vote_totals(session: AsyncSession, user_id: int) -> MyVoteTotals:
    totals = await forum_repo.author_totals(session, user_id)
    return MyVoteTotals(
        post_count=totals.post_count,
        like_count=totals.likes,
        dislike_count=totals.dislikes,
        comment_count=totals.comment_count,
        comment_like_count=totals.comment_likes,
        comment_dislike_count=totals.comment_dislikes,
    )


_COMMENTS_PREVIEW_LIMIT = 20


async def get_post_detail(
    session: AsyncSession, user_id: int, post_id: int
) -> PostDetail:
    post = await _require_post(session, post_id)
    page = await list_post_comments(
        session, user_id, post_id, _COMMENTS_PREVIEW_LIMIT, None
    )
    votes = (await _vote_state(session, PostVote, user_id, [post_id])).get(
        post_id, _NO_VOTES
    )
    author_email = (await users_repo.get_emails(session, {post.user_id}))[post.user_id]
    post_attachments = (await attachments_repo.list_for_posts(session, [post_id])).get(
        post_id, []
    )
    return PostDetail(
        **_post_out(
            post, author_email, votes, post_attachments, viewer_id=user_id
        ).model_dump(),
        comments=page.items,
        comments_next_cursor=page.next_cursor,
    )


async def list_post_comments(
    session: AsyncSession,
    user_id: int,
    post_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None,
) -> Page[CommentOut]:
    """One keyset page of a post's comments (oldest first). Raises if the post
    is gone so a stale link 404s rather than returning an empty page.
    """
    post = await _require_post(session, post_id)
    comments = await forum_repo.list_comments(session, post_id, limit, cursor)
    comments, next_cursor = slice_page(
        comments, limit, lambda c: (c.created_at, c.id)
    )
    emails = await users_repo.get_emails(session, {c.user_id for c in comments})
    votes = await _vote_state(session, CommentVote, user_id, [c.id for c in comments])
    comment_attachments = await attachments_repo.list_for_comments(
        session, [c.id for c in comments]
    )
    items = [
        _comment_out(
            c,
            emails[c.user_id],
            votes.get(c.id, _NO_VOTES),
            comment_attachments.get(c.id, []),
            post=post,
            viewer_id=user_id,
        )
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
    post = await _require_post(session, post_id)
    comment = await forum_repo.create_comment(session, post_id, user.id, body)
    attachments = await _claim_attachments_for_comment(
        session, attachment_ids or [], user, comment.id
    )
    # target_id is the comment id, so every comment notifies separately;
    # comment_id is carried only so deleting the comment cascades this away.
    await notifications_service.emit(
        session,
        recipient_id=post.user_id,
        actor_id=user.id,
        kind="post_comment",
        target_id=comment.id,
        post_id=post_id,
        comment_id=comment.id,
    )
    return _comment_out(
        comment,
        author_email=user.email,
        votes=_NO_VOTES,
        attachments=attachments,
        post=post,
        viewer_id=user.id,
    )


async def edit_comment(
    session: AsyncSession, user: User, comment_id: int, body: str
) -> CommentOut:
    """Owner-only; sets edited_at. Attachments are not changed on edit."""
    existing = await _require_owned_comment(session, user.id, comment_id)
    # The owning post carries the anonymity flag the response has to echo back.
    post = await _require_post(session, existing.post_id)
    updated = await forum_repo.update_comment(
        session, comment_id, body, edited_at=datetime.now(UTC)
    )
    comment_attachments = (
        await attachments_repo.list_for_comments(session, [comment_id])).get(comment_id, [])

    votes = (await _vote_state(session, CommentVote, user.id, [comment_id])).get(comment_id, _NO_VOTES)

    return _comment_out(
        updated,
        author_email=user.email,
        votes=votes,
        attachments=comment_attachments,
        post=post,
        viewer_id=user.id,
    )


async def delete_comment(session: AsyncSession, user_id: int, comment_id: int) -> None:
    """Owner-only. Cleans up S3 objects before cascade."""
    await _require_owned_comment(session, user_id, comment_id)
    keys = await attachments_repo.keys_for_comment(session, comment_id)
    await storage.delete_objects(keys)
    await forum_repo.delete_comment(session, comment_id)


# ---------------------------------------------------------------------------
# Votes (likes/dislikes)
# ---------------------------------------------------------------------------


async def vote_post(session: AsyncSession, user_id: int, post_id: int, value: int) -> VoteResponse:
    post = await _require_post(session, post_id)
    return await _apply_vote(
        session,
        PostVote,
        user_id,
        post_id,
        value,
        owner_id=post.user_id,
        kind="post_vote",
        post_id=post_id,
    )


async def vote_comment(session: AsyncSession, user_id: int, comment_id: int, value: int) -> VoteResponse:
    comment = await forum_repo.get_comment(session, comment_id)
    if comment is None:
        raise NotFoundError("comment")
    return await _apply_vote(
        session,
        CommentVote,
        user_id,
        comment_id,
        value,
        owner_id=comment.user_id,
        kind="comment_vote",
        post_id=comment.post_id,
        comment_id=comment_id,
    )


async def _apply_vote(
    session: AsyncSession,
    model: type[forum_repo.VoteT],
    user_id: int,
    target_id: int,
    value: int,
    *,
    owner_id: int,
    kind: NotificationKind,
    post_id: int,
    comment_id: int | None = None,
) -> VoteResponse:
    """Toggle semantics: re-sending the value you already hold clears it,
    sending the opposite switches sides.

    Notifies the owner only when a vote is set or flipped. Clearing stays
    silent and leaves any existing notification alone — telling someone their
    like was withdrawn is noise, and re-liking would only bump the row it
    already has.
    """
    existing = await forum_repo.get_vote(session, model, user_id, target_id)
    if existing is not None and existing.value == value:
        await forum_repo.remove_vote(session, model, user_id, target_id)
        my_vote = 0
    else:
        await forum_repo.set_vote(session, model, user_id, target_id, value)
        my_vote = value
        # target_id is the thing voted on, so one actor voting repeatedly
        # collapses onto a single row.
        await notifications_service.emit(
            session,
            recipient_id=owner_id,
            actor_id=user_id,
            kind=kind,
            target_id=target_id,
            value=value,
            post_id=post_id,
            comment_id=comment_id,
        )
    counts = (await forum_repo.count_votes(session, model, [target_id])).get(
        target_id, forum_repo.VoteCounts(0, 0)
    )
    return VoteResponse(
        like_count=counts.likes, dislike_count=counts.dislikes, my_vote=my_vote
    )


async def _voter_page(
    session: AsyncSession,
    model: type[forum_repo.VoteT],
    target_id: int,
    limit: int,
    value: int | None,
    cursor: int | None,
) -> Page[VoterOut]:
    """One keyset page of voters, with emails joined in one batched query."""
    rows = await forum_repo.list_voters(
        session, model, target_id, limit, value=value, cursor=cursor
    )
    rows, next_cursor = slice_page_by_id(rows, limit, lambda v: v.id)
    emails = await users_repo.get_emails(session, {v.user_id for v in rows})
    return Page(
        items=[VoterOut(email=emails[v.user_id], value=v.value) for v in rows],
        next_cursor=next_cursor,
    )


async def list_post_voters(
    session: AsyncSession,
    user_id: int,
    post_id: int,
    limit: int,
    value: int | None = None,
    cursor: int | None = None,
) -> Page[VoterOut]:
    """Who voted on a post — author only.

    NotOwnerError (403), not NotFoundError: the post itself is public, so
    hiding its existence would be pointless. Only the voter list is private.
    This deliberately differs from conversations, where existence *is* the
    secret.
    """
    post = await _require_post(session, post_id)
    if post.user_id != user_id:
        raise NotOwnerError()
    return await _voter_page(session, PostVote, post_id, limit, value, cursor)


async def list_comment_voters(
    session: AsyncSession,
    user_id: int,
    comment_id: int,
    limit: int,
    value: int | None = None,
    cursor: int | None = None,
) -> Page[VoterOut]:
    """Who voted on a comment — the comment's author only.

    Ownership follows the voted-on thing, so authoring the post a comment sits
    under does not grant a view of that comment's voters.
    """
    comment = await forum_repo.get_comment(session, comment_id)
    if comment is None:
        raise NotFoundError("comment")
    if comment.user_id != user_id:
        raise NotOwnerError()
    return await _voter_page(session, CommentVote, comment_id, limit, value, cursor)


def check_rate_limit(user_id: int) -> None:
    """Phase-2 guardrail: raise when the user exceeds posting rate limits."""
    raise NotImplementedError
