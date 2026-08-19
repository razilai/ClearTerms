"""HTTP layer.

FastAPI routers and request/response wiring only — no business logic.
Routes validate input with app.schemas and delegate to app.services.
"""

from fastapi import APIRouter

from app.api import (
    analysis,
    auth,
    forum,
    history,
    messages,
    notifications,
    preferences,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(preferences.router)
api_router.include_router(analysis.router)
api_router.include_router(history.router)
api_router.include_router(forum.router)
api_router.include_router(messages.router)
api_router.include_router(notifications.router)
