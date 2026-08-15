import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.api.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.db.engine import SessionFactory, init_db
from app.services.queue import queue
from app.services.rate_limit import sweep_loop


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    await init_db()
    await queue.start(SessionFactory)
    # Background purge of expired rate-limit rows; cancelled on shutdown.
    sweep_task = asyncio.create_task(sweep_loop())
    yield
    sweep_task.cancel()
    await queue.stop()


app = FastAPI(title="ClearTerms", lifespan=lifespan)
app.include_router(api_router)
register_exception_handlers(app)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "ClearTerms", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
