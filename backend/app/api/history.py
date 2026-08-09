from fastapi import APIRouter

from app.api.deps import CurrentUserDep, PageParamsDep, SessionDep
from app.schemas.history import HistoryEntryOut
from app.schemas.pagination import Page
from app.services import history as history_service

# Handlers delegate to app.services.history — no business logic here.
router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=Page[HistoryEntryOut])
async def get_history(
    session: SessionDep, user: CurrentUserDep, page: PageParamsDep
) -> Page[HistoryEntryOut]:
    return await history_service.list_history(
        session, user.id, page.limit, page.cursor
    )
