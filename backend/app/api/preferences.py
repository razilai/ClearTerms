from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.preferences import PreferencesResponse, PreferencesUpdate

# Handlers delegate to app.services.preferences — no business logic here.
router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=PreferencesResponse)
async def get_preferences(
    session: SessionDep, user: CurrentUserDep
) -> PreferencesResponse:
    raise NotImplementedError


@router.put("", response_model=PreferencesResponse)
async def update_preferences(
    body: PreferencesUpdate, session: SessionDep, user: CurrentUserDep
) -> PreferencesResponse:
    raise NotImplementedError
