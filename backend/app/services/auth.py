"""Auth: signup, login, JWT issue/verify, password hashing."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def signup(session: AsyncSession, email: str, password: str) -> User:
    """Create the user (hashed password); raise on duplicate email."""
    raise NotImplementedError


async def login(session: AsyncSession, email: str, password: str) -> str:
    """Verify credentials and return a JWT access token."""
    raise NotImplementedError


def hash_password(password: str) -> str:
    raise NotImplementedError


def verify_password(password: str, password_hash: str) -> bool:
    raise NotImplementedError


def create_access_token(user_id: int) -> str:
    raise NotImplementedError


def decode_access_token(token: str) -> int:
    """Return the user id; raise on invalid/expired token."""
    raise NotImplementedError
