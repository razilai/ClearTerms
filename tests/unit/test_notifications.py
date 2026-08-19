"""Unit tests for the notifications model, repo and emit policy."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import notifications as notifications_repo
from app.db.repos import users
from app.models import Notification
from app.services import notifications as notifications_service
from app.services.exceptions import NotFoundError


async def _two_users(session: AsyncSession) -> tuple[int, int]:
    ada = await users.create(session, "ada@example.com", "pw")
    bob = await users.create(session, "bob@example.com", "pw")
    return ada.id, bob.id


async def test_duplicate_event_violates_the_unique_constraint(
    session: AsyncSession,
) -> None:
    """A blind second insert on the same key must fail — this constraint is
    what the emit upsert relies on to collapse repeated votes."""
    ada, bob = await _two_users(session)
    for _ in range(2):
        session.add(
            Notification(
                recipient_id=ada,
                actor_id=bob,
                kind="post_vote",
                target_id=7,
                value=1,
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_upsert_collapses_a_repeated_event_and_resurfaces_it(
    session: AsyncSession,
) -> None:
    """Second upsert on the same key updates in place: value is rewritten and
    read_at cleared, so a like -> dislike flip re-notifies rather than adding
    a row."""
    ada, bob = await _two_users(session)
    await notifications_repo.upsert(
        session, recipient_id=ada, actor_id=bob, kind="post_vote", target_id=7, value=1
    )
    first = (await notifications_repo.list_for_user(session, ada, 10))[0]
    await notifications_repo.mark_read(session, first.id, datetime.now(tz=UTC))
    assert await notifications_repo.count_unread(session, ada) == 0

    await notifications_repo.upsert(
        session, recipient_id=ada, actor_id=bob, kind="post_vote", target_id=7, value=-1
    )
    rows = await notifications_repo.list_for_user(session, ada, 10)
    assert len(rows) == 1
    assert rows[0].id == first.id
    assert rows[0].value == -1
    assert rows[0].read_at is None
    assert await notifications_repo.count_unread(session, ada) == 1


async def test_distinct_targets_are_distinct_notifications(
    session: AsyncSession,
) -> None:
    """Different target_id means a different event — this is what makes two
    comments from one actor produce two notifications."""
    ada, bob = await _two_users(session)
    for target in (1, 2):
        await notifications_repo.upsert(
            session,
            recipient_id=ada,
            actor_id=bob,
            kind="post_comment",
            target_id=target,
        )
    assert len(await notifications_repo.list_for_user(session, ada, 10)) == 2


async def test_mark_all_read_only_touches_the_owner_and_is_idempotent(
    session: AsyncSession,
) -> None:
    ada, bob = await _two_users(session)
    await notifications_repo.upsert(
        session, recipient_id=ada, actor_id=bob, kind="post_comment", target_id=1
    )
    await notifications_repo.upsert(
        session, recipient_id=bob, actor_id=ada, kind="post_comment", target_id=2
    )
    now = datetime.now(tz=UTC)
    assert await notifications_repo.mark_all_read(session, ada, now) == 1
    assert await notifications_repo.mark_all_read(session, ada, now) == 0
    assert await notifications_repo.count_unread(session, bob) == 1


async def test_emit_is_silent_for_your_own_actions(session: AsyncSession) -> None:
    """Commenting on or voting your own content must not notify you."""
    ada, _ = await _two_users(session)
    await notifications_service.emit(
        session,
        recipient_id=ada,
        actor_id=ada,
        kind="post_comment",
        target_id=1,
        post_id=None,
    )
    assert await notifications_repo.count_unread(session, ada) == 0


async def test_marking_someone_elses_notification_is_not_found(
    session: AsyncSession,
) -> None:
    """404, not 403: ids are sequential, so a 403 would confirm the row exists."""
    ada, bob = await _two_users(session)
    await notifications_repo.upsert(
        session, recipient_id=ada, actor_id=bob, kind="post_comment", target_id=1
    )
    mine = (await notifications_repo.list_for_user(session, ada, 10))[0]
    with pytest.raises(NotFoundError):
        await notifications_service.mark_read(session, bob, mine.id)
    with pytest.raises(NotFoundError):
        await notifications_service.mark_read(session, ada, mine.id + 999)
