from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Preference
from app.schemas.preferences import PreferenceItem


async def get_for_user(session: AsyncSession, user_id: int) -> list[Preference]:
    result = await session.execute(
        select(Preference).where(Preference.user_id == user_id)
    )
    return list(result.scalars().all())

# NOTE: empty `items` clears all of the user's preferences.
# NOTE: duplicate categories within `items` raise IntegrityError (no dedupe) —
#       the preferences service must ensure no duplicate categories are passed.
async def replace_for_user(
    session: AsyncSession, user_id: int, items: list[PreferenceItem]
) -> list[Preference]:
    # Scoped to this user only. Runs before the inserts so replacing a set that
    # reuses a category does not trip the (user_id, category) unique constraint.
    await session.execute(delete(Preference).where(Preference.user_id == user_id))

    rows = [
        Preference(user_id=user_id, category=item.category, weight=item.weight)
        for item in items
    ]
    session.add_all(rows)
    # Flush, don't commit: the caller owns the transaction boundary. This
    # populates the ids and surfaces constraint violations here.
    await session.flush()
    return rows
