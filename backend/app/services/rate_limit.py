"""Fixed-window rate limiting.

Each call to :func:`enforce` bumps a per-key counter for the current time window
and raises :class:`RateLimitError` once the count passes the limit. State lives
in the rate_limits table (see repos.rate_limit), so the limit holds across
workers and replicas — unlike an in-process counter.

The counter is committed on its **own** session, deliberately separate from the
request session. The request that triggered the check may go on to fail and roll
back (a wrong-password login does exactly this); the attempt must still count, or
the limiter wouldn't throttle failures — which for login is the whole point. An
independent, immediately-committed session decouples the increment from the
request's transaction outcome.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db import engine as engine_module
from app.db.repos import rate_limit as rate_limit_repo
from app.services.exceptions import RateLimitError

logger = logging.getLogger(__name__)


async def enforce(
    scope: str,
    identifier: str,
    limit: int,
    window_seconds: int,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Count one request against ``scope:identifier`` for the current window.

    Raises :class:`RateLimitError` (with seconds until the window ends) when the
    post-increment count exceeds ``limit``. ``session_factory`` defaults to the
    process SessionFactory, read via the engine module so tests that rebind it to
    a throwaway database are honoured.
    """
    now = datetime.now(UTC).timestamp()
    window_index = int(now // window_seconds)
    window_end = (window_index + 1) * window_seconds
    bucket = f"{scope}:{identifier}:{window_index}"
    expires_at = datetime.fromtimestamp(window_end, tz=UTC)

    factory = session_factory or engine_module.SessionFactory
    async with factory() as session:
        count = await rate_limit_repo.increment(session, bucket, expires_at)
        await session.commit()

    if count > limit:
        raise RateLimitError(retry_after=max(1, int(window_end - now)))


async def sweep_expired(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Delete counter rows whose window has ended. Returns the count removed."""
    factory = session_factory or engine_module.SessionFactory
    async with factory() as session:
        removed = await rate_limit_repo.delete_expired(session, datetime.now(UTC))
        await session.commit()
    return removed


async def sweep_loop() -> None:
    """Periodically purge expired counter rows until cancelled.

    Fixed-window rows are never revisited once their window passes, so without
    this they'd accumulate forever. Started/stopped from the app lifespan.
    """
    interval = settings.rate_limit_sweep_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            removed = await sweep_expired()
            if removed:
                logger.debug("rate-limit sweep removed %d expired rows", removed)
        except Exception:
            # A sweep failure must not kill the loop — log and try again next tick.
            logger.exception("rate-limit sweep failed")
