"""User preferences: CRUD, and verdict computation.

Verdict is computed at read time from cached category scores x the user's
preference weights (see README "Analyze once, filter per user"). Changing
preferences never re-triggers analysis.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.categories import SCORE_AGGRESSIVE
from app.db.repos import preferences as preferences_repo
from app.models import Analysis, Preference
from app.schemas.preferences import PreferenceItem
from app.services.exceptions import InvalidInputError

# Weight given to a category the user has not configured. Non-zero so a fresh
# account with no preferences still gets a meaningful verdict (any aggressive
# clause counts); a user mutes a category by saving it with weight 0.
DEFAULT_WEIGHT = 1.0


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
    """Pure function: cached category scores x preference weights -> "up" / "down".

    Placeholder policy: thumbs-down if any category the user still weights
    (missing preferences default to DEFAULT_WEIGHT) scored aggressive. Weight 0
    mutes a category. Room to grow into a weighted threshold later.
    """
    weights = {pref.category: pref.weight for pref in prefs}
    for score in scores:
        weight = weights.get(score.category, DEFAULT_WEIGHT)
        if score.score >= SCORE_AGGRESSIVE and weight > 0:
            return "down"
    return "up"
