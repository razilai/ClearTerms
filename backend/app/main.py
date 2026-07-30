from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.core.logging import setup_logging
from app.db.engine import init_db
from app.services.queue import queue


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    await init_db()
    await queue.start()
    yield
    await queue.stop()


app = FastAPI(title="ClearTerms", lifespan=lifespan)
app.include_router(api_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
