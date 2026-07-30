from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    raise NotImplementedError


async def create(session: AsyncSession, email: str, password_hash: str) -> User:
    raise NotImplementedError
