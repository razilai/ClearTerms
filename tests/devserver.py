"""Run the backend against a real in-memory SQLite DB for frontend dev.

The DB repos are implemented, so this serves the actual app — auth + forum
persist in memory for the lifetime of the process and reset on restart. No
disk, no migrations, CWD-independent.

Requests run through the app's own get_session, which commits on a clean
return, so writes persist across requests with no override here.

    uv run --project backend python tests/devserver.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
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
    # schema on this engine rather than the on-disk default. SessionFactory needs
    # patching too — it was bound to the on-disk engine at import time, and
    # get_session resolves it as a module global on every request.
    import app.db.engine as db_engine

    db_engine.engine = engine
    db_engine.SessionFactory = SessionFactory

    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
