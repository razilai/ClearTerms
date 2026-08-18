"""Unit tests: rate limiter service (own-session counting)."""


from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repos import rate_limit as rate_limit_repo
from app.models import RateLimit
from app.services import rate_limit as rate_limit_service
from app.services.exceptions import (
    RateLimitError,
)

# --- rate limiting ---
#
# Enforced on `file_session_factory` (a throwaway database with genuinely
# independent connections), not the shared-connection `session`/`client` harness:
# the whole point of the limiter is that each request's count commits on its own
# connection, independent of the request's own transaction, and a shared
# connection would hide exactly that.


class _FrozenClock:
    """Stand-in for the rate_limit module's `datetime`, with a movable now().

    enforce reads both `datetime.now(UTC)` and `datetime.fromtimestamp(...)`, so
    both are provided; `now` is frozen at `self.current` (advanceable) to control
    which fixed window a call lands in.
    """

    def __init__(self, current: float) -> None:
        self.current = current

    def now(self, tz: object = None) -> datetime:
        return datetime.fromtimestamp(self.current, tz=tz)  # type: ignore[arg-type]

    def fromtimestamp(self, ts: float, tz: object = None) -> datetime:
        return datetime.fromtimestamp(ts, tz=tz)  # type: ignore[arg-type]


async def test_rate_limit_allows_up_to_limit_then_blocks(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # limit=3: three calls pass, the fourth (count 4 > 3) trips.
    for _ in range(3):
        await rate_limit_service.enforce(
            "login", "1.2.3.4", limit=3, window_seconds=60,
            session_factory=file_session_factory,
        )
    with pytest.raises(RateLimitError) as exc:
        await rate_limit_service.enforce(
            "login", "1.2.3.4", limit=3, window_seconds=60,
            session_factory=file_session_factory,
        )
    # retry_after points at the window end: positive, no larger than the window.
    assert 0 < exc.value.retry_after <= 60


async def test_rate_limit_keys_are_independent(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # One identifier exhausts its budget; a different identifier is unaffected,
    # and a different scope for the same identifier is a separate bucket too.
    for _ in range(2):
        await rate_limit_service.enforce(
            "login", "a", limit=2, window_seconds=60,
            session_factory=file_session_factory,
        )
    with pytest.raises(RateLimitError):
        await rate_limit_service.enforce(
            "login", "a", limit=2, window_seconds=60,
            session_factory=file_session_factory,
        )
    # Different identifier — fresh counter, does not raise.
    await rate_limit_service.enforce(
        "login", "b", limit=2, window_seconds=60,
        session_factory=file_session_factory,
    )
    # Same identifier, different scope — also a fresh counter.
    await rate_limit_service.enforce(
        "analyze", "a", limit=2, window_seconds=60,
        session_factory=file_session_factory,
    )


async def test_rate_limit_window_resets(
    file_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FrozenClock(10_000.0)
    monkeypatch.setattr(rate_limit_service, "datetime", clock)

    # Exhaust the window.
    await rate_limit_service.enforce(
        "login", "ip", limit=1, window_seconds=100,
        session_factory=file_session_factory,
    )
    with pytest.raises(RateLimitError):
        await rate_limit_service.enforce(
            "login", "ip", limit=1, window_seconds=100,
            session_factory=file_session_factory,
        )

    # Advance past the window boundary → a new bucket, budget restored.
    clock.current += 100
    await rate_limit_service.enforce(
        "login", "ip", limit=1, window_seconds=100,
        session_factory=file_session_factory,
    )


async def test_sweep_expired_removes_only_past_windows(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with file_session_factory() as s:
        await rate_limit_repo.increment(s, "old:1:1", now - timedelta(seconds=1))
        await rate_limit_repo.increment(s, "live:1:1", now + timedelta(hours=1))
        await s.commit()

    removed = await rate_limit_service.sweep_expired(session_factory=file_session_factory)
    assert removed == 1

    async with file_session_factory() as s:
        rows = await s.execute(select(RateLimit.bucket))
        assert rows.scalars().all() == ["live:1:1"]
