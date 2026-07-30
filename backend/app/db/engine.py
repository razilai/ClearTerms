"""Async engine / session setup for SQLite (aiosqlite)."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create tables from Base.metadata and enable SQLite WAL mode."""
    # TODO: implement (import app.models for metadata side effects, create_all, PRAGMA journal_mode=WAL)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
