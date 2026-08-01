"""Shared FastAPI dependencies: db session and authenticated user."""

from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.models import User
from app.services import auth as auth_service
from app.services.exceptions import InvalidTokenError

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Declares the OAuth2 password flow in OpenAPI (Swagger's Authorize button
# works) and 401s on a missing/malformed Authorization header.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

_UNAUTHORIZED = HTTPException(
    status_code=401,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    session: SessionDep,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    try:
        user_id = auth_service.decode_access_token(token)
    except InvalidTokenError:
        raise _UNAUTHORIZED from None
    user = await auth_service.get_user_by_id(session, user_id)
    if user is None:
        raise _UNAUTHORIZED
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
