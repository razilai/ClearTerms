"""Atomic fixed-window counter, backed by the rate_limits table."""

from datetime import datetime
from typing import cast

from sqlalchemy import CursorResult, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rate_limit import RateLimit


async def increment(session: AsyncSession, bucket: str, expires_at: datetime) -> int:
    """Bump the counter for ``bucket`` by one and return the new value.

    A single statement so concurrent requests can't race a read-modify-write:
    Postgres serializes the conflicting upserts on the primary key. The first
    request in a window inserts count=1 with the window's expiry; every later
    one takes the DO UPDATE branch and increments, leaving expires_at as first
    set. RETURNING hands back the post-increment count for the limit check.
    """
    stmt = (
        pg_insert(RateLimit)
        .values(bucket=bucket, count=1, expires_at=expires_at)
        .on_conflict_do_update(
            index_elements=["bucket"],
            set_={"count": RateLimit.count + 1},
        )
        .returning(RateLimit.count)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def delete_expired(session: AsyncSession, now: datetime) -> int:
    """Delete counter rows whose window has ended; return how many were removed."""
    result = await session.execute(delete(RateLimit).where(RateLimit.expires_at < now))
    return cast("CursorResult[object]", result).rowcount
