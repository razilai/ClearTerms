"""Auth: signup, login, JWT issue/verify, password hashing."""

from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.repos import users as users_repo
from app.models import User
from app.schemas.auth import TokenPayload
from app.services.exceptions import (
    DuplicateEmailError,
    InvalidCredentialsError,
    InvalidTokenError,
)

# Argon2 hasher; module-level because construction is not free.
_pwd = PasswordHash.recommended()

# Verified against when the email is unknown, so login costs one argon2
# verification either way and response time does not reveal whether an
# email is registered.
_DUMMY_HASH = _pwd.hash("dummy-password")

# Tolerated clock skew between token issuer and verifier.
_LEEWAY_SECONDS = 10


async def signup(session: AsyncSession, email: str, password: str) -> User:
    """Create the user (hashed password); raise on duplicate email."""
    email = email.lower()
    if await users_repo.get_by_email(session, email) is not None:
        raise DuplicateEmailError
    return await users_repo.create(session, email, hash_password(password))


async def login(session: AsyncSession, email: str, password: str) -> str:
    """Verify credentials and return a JWT access token."""
    # Login arrives as OAuth2 form data, so SignupRequest's length caps never
    # run on it — enforce them here, and *before* touching the hasher: argon2
    # on an unbounded password is the CPU-burn this guards against, and the
    # dummy-hash path below would pay that cost too. Rejecting as invalid
    # credentials rather than 422 leaks nothing (an over-long input cannot
    # match a stored hash anyway) and the length is the caller's own input.
    if (
        len(email) > settings.max_email_chars
        or len(password) > settings.max_password_chars
    ):
        raise InvalidCredentialsError
    user = await users_repo.get_by_email(session, email.lower())
    if user is None:
        _pwd.verify(password, _DUMMY_HASH)
        raise InvalidCredentialsError
    valid, migrated_hash = _pwd.verify_and_update(password, user.password_hash)
    if not valid:
        raise InvalidCredentialsError
    if migrated_hash is not None:
        # Argon2 parameters changed since this hash was made; upgrade it.
        await users_repo.update_password_hash(session, user.id, migrated_hash)
    return create_access_token(user.id)


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await users_repo.get_by_id(session, user_id)


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd.verify(password, password_hash)


def create_access_token(user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {
        # PyJWT >=2.10 rejects non-string "sub" on decode.
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> int:
    """Return the user id; raise on invalid/expired token."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            # Without "require", a token missing exp would never expire.
            options={"require": ["exp", "iat", "sub"]},
            leeway=_LEEWAY_SECONDS,
        )
        return TokenPayload.model_validate(claims).sub
    except (jwt.PyJWTError, ValidationError) as exc:
        raise InvalidTokenError from exc
