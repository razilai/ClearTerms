from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Preference
from app.schemas.preferences import PreferenceItem


async def get_for_user(session: AsyncSession, user_id: int) -> list[Preference]:
    raise NotImplementedError


async def replace_for_user(
    session: AsyncSession, user_id: int, items: list[PreferenceItem]
) -> list[Preference]:
    raise NotImplementedError
