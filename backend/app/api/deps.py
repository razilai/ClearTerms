"""Shared FastAPI dependencies: db session and authenticated user."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.models import User
from app.schemas.pagination import decode_cursor
from app.services import auth as auth_service
from app.services.exceptions import InvalidTokenError

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass
class PageParams:
    """Decoded keyset paging inputs for a list route: a clamped page size and
    the optional ``(created_at, id)`` cursor. Decoding a malformed cursor is a
    400 here so services stay free of HTTP concerns and only see the tuple.
    """

    limit: int
    cursor: tuple[datetime, int] | None


def page_params(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> PageParams:
    if cursor is None:
        return PageParams(limit=limit, cursor=None)
    try:
        return PageParams(limit=limit, cursor=decode_cursor(cursor))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cursor") from None


PageParamsDep = Annotated[PageParams, Depends(page_params)]

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
