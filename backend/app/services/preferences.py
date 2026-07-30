"""User preferences: CRUD, and verdict computation.

Verdict is computed at read time from cached category scores x the user's
preference weights (see README "Analyze once, filter per user"). Changing
preferences never re-triggers analysis.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, Preference
from app.schemas.preferences import PreferenceItem


async def get_preferences(session: AsyncSession, user_id: int) -> list[Preference]:
    raise NotImplementedError


async def update_preferences(
    session: AsyncSession, user_id: int, items: list[PreferenceItem]
) -> list[Preference]:
    raise NotImplementedError


def compute_verdict(scores: list[Analysis], prefs: list[Preference]) -> str:
    """Pure function: cached category scores x preference weights -> "up" / "down"."""
    raise NotImplementedError
