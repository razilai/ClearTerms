from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_emails(
    session: AsyncSession, user_ids: Iterable[int]
) -> dict[int, str]:
    """Map user id -> email for the given ids; unknown ids are absent."""
    ids = list(user_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(User.id, User.email).where(User.id.in_(ids))
    )
    return {uid: email for uid, email in result.all()}


async def update_password_hash(
    session: AsyncSession, user_id: int, password_hash: str
) -> None:
    user = await session.get(User, user_id)
    if user is not None:
        user.password_hash = password_hash
        await session.flush()


async def create(session: AsyncSession, email: str, password_hash: str) -> User:
    user = User(email=email, password_hash=password_hash)
    session.add(user)
    # Flush, don't commit: the caller owns the transaction boundary. This
    # populates user.id and surfaces the unique-email violation here.
    await session.flush()
    return user
