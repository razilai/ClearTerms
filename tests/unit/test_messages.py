"""Unit tests for direct-message repositories and shared attachment ownership."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import attachments as attachments_repo
from app.db.repos import messages as messages_repo
from app.db.repos import users
from app.models import Attachment, Post


async def _two_users(session: AsyncSession) -> tuple[int, int]:
    ada = await users.create(session, "ada@example.com", "pw")
    bob = await users.create(session, "bob@example.com", "pw")
    return ada.id, bob.id


async def test_conversation_pair_is_canonical_and_idempotent(
    session: AsyncSession,
) -> None:
    ada, bob = await _two_users(session)
    assert messages_repo.participant_pair(bob, ada) == (ada, bob)

    first = await messages_repo.get_or_create(session, ada, bob)
    again = await messages_repo.get_or_create(session, bob, ada)
    assert (first.user_a_id, first.user_b_id) == (ada, bob)
    assert again.id == first.id


async def test_self_conversation_violates_the_database_constraint(
    session: AsyncSession,
) -> None:
    ada, _ = await _two_users(session)
    with pytest.raises(IntegrityError):
        await messages_repo.get_or_create(session, ada, ada)


async def test_conversation_inbox_covers_both_users_and_keyset_pages(
    session: AsyncSession,
) -> None:
    ada, bob = await _two_users(session)
    cy = (await users.create(session, "cy@example.com", "pw")).id
    ada_bob = await messages_repo.get_or_create(session, ada, bob)
    ada_cy = await messages_repo.get_or_create(session, ada, cy)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await messages_repo.touch(session, ada_bob.id, base)
    await messages_repo.touch(session, ada_cy.id, base + timedelta(minutes=1))

    page = await messages_repo.list_for_user(session, ada, limit=1)
    assert [conversation.id for conversation in page] == [ada_cy.id, ada_bob.id]
    following = await messages_repo.list_for_user(
        session, ada, limit=1, cursor=(page[0].last_message_at, page[0].id)
    )
    assert [conversation.id for conversation in following] == [ada_bob.id]
    assert [
        conversation.id
        for conversation in await messages_repo.list_for_user(session, bob, 10)
    ] == [ada_bob.id]


async def test_messages_page_newest_first_and_latest_preview(
    session: AsyncSession,
) -> None:
    ada, bob = await _two_users(session)
    conversation = await messages_repo.get_or_create(session, ada, bob)
    sent = [
        await messages_repo.create_message(session, conversation.id, ada, f"m{i}")
        for i in range(3)
    ]
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index, message in enumerate(sent):
        message.created_at = base + timedelta(minutes=index)
    await session.flush()

    page = await messages_repo.list_messages(session, conversation.id, limit=2)
    assert [message.body for message in page] == ["m2", "m1", "m0"]
    following = await messages_repo.list_messages(
        session, conversation.id, limit=2, cursor=(page[1].created_at, page[1].id)
    )
    assert [message.body for message in following] == ["m0"]
    latest = await messages_repo.latest_by_conversation(session, [conversation.id])
    assert latest[conversation.id].body == "m2"


async def test_unread_counts_exclude_messages_you_sent(session: AsyncSession) -> None:
    ada, bob = await _two_users(session)
    conversation = await messages_repo.get_or_create(session, ada, bob)
    await messages_repo.create_message(session, conversation.id, ada, "from ada")
    await messages_repo.create_message(session, conversation.id, bob, "from bob")

    assert await messages_repo.count_unread(session, bob, [conversation.id]) == {
        conversation.id: 1
    }
    assert await messages_repo.count_unread_total(session, ada) == 1
    assert (
        await messages_repo.mark_read(session, conversation.id, bob, datetime.now(UTC))
        == 1
    )
    assert await messages_repo.count_unread_total(session, bob) == 0


async def test_message_attachments_are_not_orphans_or_double_owned(
    session: AsyncSession,
) -> None:
    ada, bob = await _two_users(session)
    conversation = await messages_repo.get_or_create(session, ada, bob)
    message = await messages_repo.create_message(session, conversation.id, ada, "hi")
    claimed = await attachments_repo.create(
        session,
        user_id=ada,
        media_type="image",
        mime="image/png",
        size_bytes=1,
        original_key="claimed",
    )
    unclaimed = await attachments_repo.create(
        session,
        user_id=ada,
        media_type="image",
        mime="image/png",
        size_bytes=1,
        original_key="unclaimed",
    )
    await attachments_repo.claim_for_message(session, [claimed.id], ada, message.id)
    cutoff = (datetime.now(UTC) + timedelta(minutes=1)).timestamp()
    swept = {
        row.id for row in await attachments_repo.list_unlinked_before(session, cutoff)
    }
    assert claimed.id not in swept
    assert unclaimed.id in swept

    post = Post(user_id=ada, title="post", body="body")
    session.add(post)
    await session.flush()
    session.add(
        Attachment(
            user_id=ada,
            post_id=post.id,
            message_id=message.id,
            media_type="image",
            status="ready",
            mime="image/png",
            size_bytes=1,
            original_key="double",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
