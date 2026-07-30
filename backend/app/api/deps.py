"""Shared FastAPI dependencies: db session and authenticated user."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]

bearer_scheme = HTTPBearer()


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> User:
    """Decode the bearer JWT (services.auth.decode_access_token), load the user,
    401 on failure."""
    raise NotImplementedError


CurrentUserDep = Annotated[User, Depends(get_current_user)]
