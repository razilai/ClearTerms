from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import SessionDep, rate_limit_login
from app.schemas.auth import SignupRequest, TokenResponse
from app.services import auth as auth_service

# Handlers delegate to app.services.auth — no business logic here.
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(body: SignupRequest, session: SessionDep) -> TokenResponse:
    user = await auth_service.signup(
        session, body.email, body.password.get_secret_value()
    )
    return TokenResponse(access_token=auth_service.create_access_token(user.id))


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit_login)],
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep
) -> TokenResponse:
    # OAuth2 password flow: form-encoded, username field carries the email.
    token = await auth_service.login(session, form.username, form.password)
    return TokenResponse(access_token=token)
