"""Unit tests for the notifications model, repo and emit policy."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos import users
from app.models import Notification


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
