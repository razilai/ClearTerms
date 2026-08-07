from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.history import HistoryResponse
from app.services import history as history_service

# Handlers delegate to app.services.history — no business logic here.
router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=HistoryResponse)
async def get_history(session: SessionDep, user: CurrentUserDep) -> HistoryResponse:
    entries = await history_service.list_history(session, user.id)
    return HistoryResponse(entries=entries)
