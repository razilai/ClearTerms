"""User preferences: CRUD, and verdict computation.

Preferences are a binary checklist: each clause category is either on or off.
Verdict is computed at read time by ignoring the cached scores of categories
the user switched off (see README "Analyze once, filter per user"). The agent
always scores every category regardless, so switching one back on reveals it in
analyses that already exist — nothing is re-run, nothing was skipped.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.categories import SCORE_AGGRESSIVE
from app.db.repos import preferences as preferences_repo
from app.models import Analysis, Preference
from app.schemas.preferences import PreferenceItem
from app.services.exceptions import InvalidInputError

# Applied to a category the user has not configured. On, so a fresh account
# with no preference rows still gets a meaningful verdict (any aggressive clause
# counts); a user mutes a category by saving it unchecked.
DEFAULT_ENABLED = True


async def get_preferences(session: AsyncSession, user_id: int) -> list[Preference]:
    return await preferences_repo.get_for_user(session, user_id)


async def update_preferences(
    session: AsyncSession, user_id: int, items: list[PreferenceItem]
) -> list[Preference]:
    # replace_for_user has no dedupe: a duplicate category would trip the
    # (user_id, category) unique constraint mid-flush, so reject it up front.
    categories = [item.category for item in items]
    if len(categories) != len(set(categories)):
        raise InvalidInputError("duplicate category in preferences")
    return await preferences_repo.replace_for_user(session, user_id, items)


def compute_verdict(scores: list[Analysis], prefs: list[Preference]) -> str:
    """Pure function: cached category scores x the user's checklist -> "up" / "down".

    Thumbs-down if any category the user still has switched on (categories with
    no preference row default to DEFAULT_ENABLED) scored aggressive. An
    unchecked category is invisible here for the same reason it is hidden from
    the report: the user has said it does not concern them.
    """
    enabled = {pref.category: pref.enabled for pref in prefs}
    for score in scores:
        if score.score >= SCORE_AGGRESSIVE and enabled.get(
            score.category, DEFAULT_ENABLED
        ):
            return "down"
    return "up"
