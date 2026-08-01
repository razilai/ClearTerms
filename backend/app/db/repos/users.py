from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    # TODO(db): SELECT by unique email index.
    raise NotImplementedError


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    # TODO(db): SELECT by primary key.
    raise NotImplementedError


async def get_emails(
    session: AsyncSession, user_ids: Iterable[int]
) -> dict[int, str]:
    """Map user id -> email for the given ids."""
    # TODO(db): batch SELECT id, email WHERE id IN (...) — avoids N+1 when
    # rendering author_email on posts/comments.
    raise NotImplementedError


async def update_password_hash(
    session: AsyncSession, user_id: int, password_hash: str
) -> None:
    """Persist a hash migrated by pwdlib's verify_and_update on login."""
    # TODO(db): UPDATE users SET password_hash WHERE id.
    raise NotImplementedError


async def create(session: AsyncSession, email: str, password_hash: str) -> User:
    # TODO(db): INSERT; translate IntegrityError on the unique email constraint
    # into services.exceptions.DuplicateEmailError (covers the check-then-insert
    # race in services.auth.signup).
    raise NotImplementedError
