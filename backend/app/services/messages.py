"""Direct messaging business logic.

Participant checks live here, as they do for forum ownership. Services return
API schemas (not ORM rows) because every read needs participant emails joined
in — db work the api layer is not allowed to do (mirrors the forum service).

A conversation stores its pair as (user_a_id, user_b_id); nothing above this
layer sees those columns. _other_id is the single choke point that turns the
pair plus a viewer into "the person you are talking to".
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.repos import attachments as attachments_repo
from app.db.repos import messages as messages_repo
from app.db.repos import users as users_repo
from app.models import Conversation, Message, User
from app.models.attachment import Attachment
from app.schemas.messages import (
    ConversationDetail,
    ConversationOut,
    MarkReadResponse,
    MessageOut,
    UnreadTotal,
)
from app.schemas.pagination import Page, slice_page
from app.services import media as media_service
from app.services import notifications as notifications_service
from app.services.exceptions import (
    InvalidInputError,
    NotFoundError,
    TooManyAttachmentsError,
)

# One screen of history when a thread is opened; older pages come from
# list_messages with a cursor.
_MESSAGES_PREVIEW_LIMIT = 30


def _other_id(conversation: Conversation, viewer_id: int) -> int:
    """The participant who is not the viewer."""
    return (
        conversation.user_b_id
        if conversation.user_a_id == viewer_id
        else conversation.user_a_id
    )


def _message_out(
    message: Message,
    sender_email: str,
    attachments: list[Attachment] | None = None,
) -> MessageOut:
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_email=sender_email,
        body=message.body,
        created_at=message.created_at,
        read_at=message.read_at,
        attachments=[
            media_service.attachment_out(a) for a in attachments or []
        ],
    )


async def _claim_attachments(
    session: AsyncSession, attachment_ids: list[int], user: User, message_id: int
) -> list[Attachment]:
    """Link uploaded attachments to a message; raise on any mismatch.

    Mirrors the forum's claim helpers: the repo only links rows that are
    user-owned and still unlinked, and the gap between requested and claimed is
    what surfaces someone else's id or a double-claim.
    """
    if not attachment_ids:
        return []
    rows = await attachments_repo.claim_for_message(
        session, attachment_ids, user.id, message_id
    )
    claimed = {a.id for a in rows if a.message_id == message_id}
    for attachment_id in attachment_ids:
        if attachment_id not in claimed:
            raise NotFoundError("attachment")
    return rows


async def _require_participant(
    session: AsyncSession, user_id: int, conversation_id: int
) -> Conversation:
    """Load a conversation the caller is actually in.

    A non-participant gets NotFoundError, not NotOwnerError: conversation ids
    are sequential, so a 403 would confirm that two other people are talking to
    each other. Forum resources are public, so they can afford to say "yours or
    not"; a private thread cannot.
    """
    conversation = await messages_repo.get_conversation(session, conversation_id)
    if conversation is None:
        raise NotFoundError("conversation")
    if user_id not in (conversation.user_a_id, conversation.user_b_id):
        raise NotFoundError("conversation")
    return conversation


async def _hydrate(
    session: AsyncSession,
    viewer_id: int,
    conversations: list[Conversation],
    emails: dict[int, str],
) -> list[ConversationOut]:
    """Attach preview + unread count to conversations, two queries for the lot.

    ``emails`` must already cover both sides of every pair; a preview's sender
    is always one of the two participants, so no extra lookup is needed for it.
    """
    ids = [c.id for c in conversations]
    previews = await messages_repo.latest_by_conversation(session, ids)
    unread = await messages_repo.count_unread(session, viewer_id, ids)
    # One more batched query so a preview of an attachments-only message still
    # renders something, rather than an empty row.
    preview_attachments = await attachments_repo.list_for_messages(
        session, [m.id for m in previews.values()]
    )
    return [
        ConversationOut(
            id=c.id,
            other_email=emails[_other_id(c, viewer_id)],
            last_message_at=c.last_message_at,
            created_at=c.created_at,
            last_message=(
                _message_out(
                    previews[c.id],
                    emails[previews[c.id].sender_id],
                    preview_attachments.get(previews[c.id].id, []),
                )
                if c.id in previews
                else None
            ),
            unread_count=unread.get(c.id, 0),
        )
        for c in conversations
    ]


async def start_conversation(
    session: AsyncSession, user: User, recipient_email: str
) -> ConversationOut:
    """Open the thread with ``recipient_email``, or return the existing one.

    Idempotent by design: the pair maps to one conversation, so "message this
    person" from anywhere in the UI lands in the same thread.
    """
    recipient = await users_repo.get_by_email(session, recipient_email)
    if recipient is None:
        raise NotFoundError("user")
    if recipient.id == user.id:
        # Caught here rather than at ck_conversations_user_order, which would
        # surface as a 500 instead of a 400.
        raise InvalidInputError("cannot start a conversation with yourself")

    conversation = await messages_repo.get_or_create(session, user.id, recipient.id)
    emails = {user.id: user.email, recipient.id: recipient.email}
    return (await _hydrate(session, user.id, [conversation], emails))[0]


async def list_conversations(
    session: AsyncSession,
    user_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None,
) -> Page[ConversationOut]:
    """One keyset page of the inbox, most recent activity first."""
    rows = await messages_repo.list_for_user(session, user_id, limit, cursor)
    rows, next_cursor = slice_page(rows, limit, lambda c: (c.last_message_at, c.id))
    # The viewer can send in any of these, so their own email is needed for
    # previews of messages they wrote.
    emails = await users_repo.get_emails(
        session, {_other_id(c, user_id) for c in rows} | {user_id}
    )
    items = await _hydrate(session, user_id, rows, emails)
    return Page(items=items, next_cursor=next_cursor)


async def list_messages(
    session: AsyncSession,
    user_id: int,
    conversation_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None,
) -> Page[MessageOut]:
    """One keyset page of a thread, newest first. 404s for non-participants."""
    conversation = await _require_participant(session, user_id, conversation_id)
    rows = await messages_repo.list_messages(session, conversation_id, limit, cursor)
    rows, next_cursor = slice_page(rows, limit, lambda m: (m.created_at, m.id))
    emails = await users_repo.get_emails(
        session, {conversation.user_a_id, conversation.user_b_id}
    )
    attachments = await attachments_repo.list_for_messages(
        session, [m.id for m in rows]
    )
    items = [
        _message_out(m, emails[m.sender_id], attachments.get(m.id, [])) for m in rows
    ]
    return Page(items=items, next_cursor=next_cursor)


async def get_conversation_detail(
    session: AsyncSession, user_id: int, conversation_id: int
) -> ConversationDetail:
    """A thread plus its first page of messages, for opening it in one request."""
    conversation = await _require_participant(session, user_id, conversation_id)
    emails = await users_repo.get_emails(
        session, {conversation.user_a_id, conversation.user_b_id}
    )
    out = (await _hydrate(session, user_id, [conversation], emails))[0]
    page = await list_messages(
        session, user_id, conversation_id, _MESSAGES_PREVIEW_LIMIT, None
    )
    return ConversationDetail(
        **out.model_dump(),
        messages=page.items,
        messages_next_cursor=page.next_cursor,
    )


async def send_message(
    session: AsyncSession,
    user: User,
    conversation_id: int,
    body: str,
    attachment_ids: list[int] | None = None,
) -> MessageOut:
    """Post into a thread the sender is part of, and float it up the inbox."""
    attachment_ids = attachment_ids or []
    if len(attachment_ids) > settings.max_attachments_per_item:
        raise TooManyAttachmentsError()
    if not body.strip() and not attachment_ids:
        raise InvalidInputError("a message needs text or an attachment")

    conversation = await _require_participant(session, user.id, conversation_id)
    message = await messages_repo.create_message(
        session, conversation_id, user.id, body
    )
    attachments = await _claim_attachments(
        session, attachment_ids, user, message.id
    )
    # Bump with the message's own timestamp rather than a fresh clock reading,
    # so last_message_at always equals the newest message's created_at.
    await messages_repo.touch(session, conversation_id, message.created_at)
    # target_id is the message id, so each message notifies separately. This is
    # independent of the §4 unread badge, which counts messages not yet opened
    # rather than events not yet acknowledged.
    await notifications_service.emit(
        session,
        recipient_id=_other_id(conversation, user.id),
        actor_id=user.id,
        kind="dm",
        target_id=message.id,
        conversation_id=conversation_id,
    )
    return _message_out(message, user.email, attachments)


async def mark_read(
    session: AsyncSession, user_id: int, conversation_id: int
) -> MarkReadResponse:
    """Clear the other party's unread messages in this thread."""
    await _require_participant(session, user_id, conversation_id)
    marked = await messages_repo.mark_read(
        session, conversation_id, user_id, datetime.now(tz=UTC)
    )
    return MarkReadResponse(marked_count=marked)


async def unread_total(session: AsyncSession, user_id: int) -> UnreadTotal:
    """Unread messages across every conversation, for the notification badge."""
    return UnreadTotal(
        unread_count=await messages_repo.count_unread_total(session, user_id)
    )
