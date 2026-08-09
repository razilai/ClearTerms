"""Run the backend against a real in-memory SQLite DB for frontend dev.

The DB repos are implemented, so this serves the actual app — auth + forum
persist in memory for the lifetime of the process and reset on restart. No
disk, no migrations, CWD-independent.

The app's repos flush but do not commit, and the request-transaction boundary
is not wired yet, so a bare per-request session would roll back on close and
nothing would survive to the next request. The session override below commits
on a clean request so writes persist across requests — which is the whole point
of a dev server. Drop the override once the app owns its own commit boundary.

    uv run --project backend python tests/devserver.py
"""

import sys
from collections.abc import AsyncIterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def main() -> None:
    # StaticPool keeps every checkout on one connection, so the ``:memory:`` DB
    # survives across requests instead of vanishing when a connection recycles.
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    # Patch the engine before importing app.main so lifespan.init_db builds the
    # schema on this engine rather than the on-disk default. SessionFactory is
    # a separate object bound to the on-disk engine at import time, so it needs
    # its own patch too — app.main's lifespan now imports it directly to hand
    # the analysis queue its worker sessions, and without this the queue would
    # silently open ./data/clearterms.db instead of this in-memory database.
    import app.db.engine as db_engine

    db_engine.engine = engine
    db_engine.SessionFactory = SessionFactory

    from app.db.engine import get_session
    from app.main import app

    async def _committing_session() -> AsyncIterator[AsyncSession]:
        async with SessionFactory() as session:
            yield session
            # Only reached on a clean request; a raising route propagates into
            # the generator here and skips the commit, so the context manager
            # rolls back.
            await session.commit()

    app.dependency_overrides[get_session] = _committing_session

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
