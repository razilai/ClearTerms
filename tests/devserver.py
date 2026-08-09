"""Run the backend against a throwaway Postgres container for frontend dev.

Serves the real app — auth + forum + analysis persist for the lifetime of the
process and reset on restart, because the container (and its data) is torn down
when this exits. Matches the production database (Postgres), needs Docker, and
is CWD-independent. No Alembic here: the schema is built directly from the ORM
metadata, since a scratch db doesn't need migration history.

Requests run through the app's own get_session, which commits on a clean
return, so writes persist across requests with no override here.

    uv run --project backend python tests/devserver.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer


def main() -> None:
    with PostgresContainer("postgres:16", driver="asyncpg") as pg:
        url = pg.get_connection_url()

        # Build the schema on a throwaway engine/loop, then dispose it: the app
        # creates its own connections inside uvicorn's event loop, and asyncpg
        # connections cannot cross loops.
        from app.models import Base

        async def _create_schema() -> None:
            engine = create_async_engine(url)
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
            finally:
                await engine.dispose()

        asyncio.run(_create_schema())

        # Patch the engine before importing app.main so lifespan.init_db (a
        # connectivity check now) and every request use this container's db.
        # SessionFactory needs patching too — get_session resolves it as a module
        # global on every request, and app.main's lifespan imports it directly to
        # hand the analysis queue its worker sessions.
        import app.db.engine as db_engine

        app_engine = create_async_engine(url)
        db_engine.engine = app_engine
        db_engine.SessionFactory = async_sessionmaker(
            app_engine, expire_on_commit=False
        )

        from app.main import app

        uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
