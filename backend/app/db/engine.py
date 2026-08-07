"""Async engine / session setup for SQLite (aiosqlite)."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create tables from Base.metadata and enable SQLite WAL mode."""
    # Imported for the side effect of registering every table on Base.metadata.
    import app.models  # noqa: F401
    from app.models.base import Base

    async with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.run_sync(Base.metadata.create_all)


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
