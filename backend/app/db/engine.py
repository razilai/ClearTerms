"""Async engine / session setup for PostgreSQL (asyncpg)."""

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# pool_pre_ping recycles connections the server dropped (idle timeouts, restarts)
# instead of handing a dead one to the first request after the gap. Pool sizing
# and the per-connection statement_timeout are tuned from settings; the timeout
# rides on asyncpg's server_settings so every connection gets it at checkout.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    connect_args={
        "server_settings": {"statement_timeout": str(settings.db_statement_timeout_ms)}
    },
)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Verify the database is reachable at startup.

    Schema is owned by Alembic (``alembic upgrade head``), run as a deploy step —
    not created here. This only opens a connection so lifespan fails fast if the
    database is down rather than 500ing on the first request.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def get_session() -> AsyncIterator[AsyncSession]:
    # Repos flush but never commit — the request owns the transaction boundary.
    # Commit on a clean handler return so writes persist; roll back on any error
    # (including the service-layer domain exceptions the api maps to 4xx).
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
