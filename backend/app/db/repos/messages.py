"""Direct messaging data access: conversations and their messages."""

from collections.abc import Iterable
from datetime import datetime
from typing import cast

from sqlalchemy import CursorResult, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message

# ---------------------------------------------------------------------------
# Conversation operations
# ---------------------------------------------------------------------------


def participant_pair(user_id: int, other_id: int) -> tuple[int, int]:
    """Canonical (user_a_id, user_b_id) for a pair — smaller id first.

    Mirrors ck_conversations_user_order, which is what makes
    UniqueConstraint(user_a_id, user_b_id) mean "one conversation per pair"
    rather than one per ordered pair.
    """
    return (user_id, other_id) if user_id < other_id else (other_id, user_id)


async def get_conversation(
    session: AsyncSession, conversation_id: int
) -> Conversation | None:
    return await session.get(Conversation, conversation_id)


async def get_by_participants(
    session: AsyncSession, user_id: int, other_id: int
) -> Conversation | None:
    a, b = participant_pair(user_id, other_id)
    result = await session.execute(
        select(Conversation).where(
            Conversation.user_a_id == a, Conversation.user_b_id == b
        )
    )
    return result.scalar_one_or_none()


async def get_or_create(
    session: AsyncSession, user_id: int, other_id: int
) -> Conversation:
    """Fetch the pair's conversation, creating it on first contact.

    Two callers racing here both miss the lookup and both insert; the unique
    constraint turns the loser into an IntegrityError and the request rolls
    back, so a retry finds the winner's row. Passing the same id twice violates
    ck_conversations_user_order — the service rejects self-conversations before
    reaching this.
    """
    existing = await get_by_participants(session, user_id, other_id)
    if existing is not None:
        return existing

    a, b = participant_pair(user_id, other_id)
    conversation = Conversation(user_a_id=a, user_b_id=b)
    session.add(conversation)
    # Flush, don't commit: the caller owns the transaction boundary. This
    # populates conversation.id and its server defaults.
    await session.flush()
    return conversation


async def list_for_user(
    session: AsyncSession,
    user_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None = None,
) -> list[Conversation]:
    """One keyset page of a user's inbox, most recent activity first.

    Fetches ``limit + 1`` so the caller can detect a further page. Either
    participant column can be the viewer, so this ORs across both and each is
    served by its own ``(user_x_id, last_message_at)`` index.
    """
    stmt = select(Conversation).where(
        or_(Conversation.user_a_id == user_id, Conversation.user_b_id == user_id)
    )
    if cursor is not None:
        stmt = stmt.where(
            tuple_(Conversation.last_message_at, Conversation.id) < cursor
        )
    stmt = stmt.order_by(
        Conversation.last_message_at.desc(), Conversation.id.desc()
    ).limit(limit + 1)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def touch(session: AsyncSession, conversation_id: int, when: datetime) -> None:
    """Bump last_message_at so the thread sorts to the top of the inbox.

    Denormalized on purpose: ordering the inbox by a join onto each thread's
    newest message would scan every message the user has.
    """
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(last_message_at=when)
    )
    await session.flush()


# ---------------------------------------------------------------------------
# Message operations
# ---------------------------------------------------------------------------


async def create_message(
    session: AsyncSession, conversation_id: int, sender_id: int, body: str
) -> Message:
    message = Message(conversation_id=conversation_id, sender_id=sender_id, body=body)
    session.add(message)
    await session.flush()
    return message


async def get_message(session: AsyncSession, message_id: int) -> Message | None:
    return await session.get(Message, message_id)


async def list_messages(
    session: AsyncSession,
    conversation_id: int,
    limit: int,
    cursor: tuple[datetime, int] | None = None,
) -> list[Message]:
    """One keyset page of a thread, newest first.

    Descending unlike list_comments: a thread opens on the latest message and
    pages backwards through history, where a post's comments are read top-down.
    Fetches ``limit + 1``; uses ``ix_messages_conversation_created_id``.
    """
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if cursor is not None:
        stmt = stmt.where(tuple_(Message.created_at, Message.id) < cursor)
    stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def latest_by_conversation(
    session: AsyncSession, conversation_ids: Iterable[int]
) -> dict[int, Message]:
    """Map conversation id -> its newest message, for inbox previews.

    One DISTINCT ON query for the whole page; fetching the last message per
    conversation in a loop would be an N+1 on every inbox load. Conversations
    with no messages are absent.
    """
    ids = list(conversation_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id.in_(ids))
        .order_by(
            Message.conversation_id,
            Message.created_at.desc(),
            Message.id.desc(),
        )
        .distinct(Message.conversation_id)
    )
    return {m.conversation_id: m for m in result.scalars().all()}


async def count_unread(
    session: AsyncSession, user_id: int, conversation_ids: Iterable[int]
) -> dict[int, int]:
    """Map conversation id -> unread count for this user, in one grouped query.

    Unread means a message this user did not send and has not read.
    Conversations with nothing unread are absent.
    """
    ids = list(conversation_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(Message.conversation_id, func.count())
        .where(
            Message.conversation_id.in_(ids),
            Message.sender_id != user_id,
            Message.read_at.is_(None),
        )
        .group_by(Message.conversation_id)
    )
    return {conversation_id: count for conversation_id, count in result.all()}


async def count_unread_total(session: AsyncSession, user_id: int) -> int:
    """Every unread message addressed to this user, across all conversations.

    Feeds the notification badge, which is a single number and must not depend
    on which inbox page is on screen.
    """
    result = await session.execute(
        select(func.count())
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            or_(
                Conversation.user_a_id == user_id,
                Conversation.user_b_id == user_id,
            ),
            Message.sender_id != user_id,
            Message.read_at.is_(None),
        )
    )
    return result.scalar_one()


async def mark_read(
    session: AsyncSession, conversation_id: int, reader_id: int, when: datetime
) -> int:
    """Mark the other party's unread messages in this thread as read.

    Returns how many rows changed. Already-read messages keep their original
    read_at, so opening a thread twice doesn't rewrite history.
    """
    result = await session.execute(
        update(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.sender_id != reader_id,
            Message.read_at.is_(None),
        )
        .values(read_at=when)
    )
    await session.flush()
    return cast("CursorResult[object]", result).rowcount
