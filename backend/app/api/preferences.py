from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SessionDep
from app.models import Preference
from app.schemas.preferences import (
    PreferenceItem,
    PreferencesResponse,
    PreferencesUpdate,
)
from app.services import preferences as preferences_service

# Handlers delegate to app.services.preferences — no business logic here.
router = APIRouter(prefix="/preferences", tags=["preferences"])


def _response(prefs: list[Preference]) -> PreferencesResponse:
    return PreferencesResponse(
        items=[PreferenceItem(category=p.category, weight=p.weight) for p in prefs]
    )


@router.get("", response_model=PreferencesResponse)
async def get_preferences(
    session: SessionDep, user: CurrentUserDep
) -> PreferencesResponse:
    return _response(await preferences_service.get_preferences(session, user.id))


@router.put("", response_model=PreferencesResponse)
async def update_preferences(
    body: PreferencesUpdate, session: SessionDep, user: CurrentUserDep
) -> PreferencesResponse:
    prefs = await preferences_service.update_preferences(session, user.id, body.items)
    return _response(prefs)
