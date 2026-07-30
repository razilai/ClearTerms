from fastapi import APIRouter

from app.api.deps import SessionDep
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse

# Handlers delegate to app.services.auth — no business logic here.
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(body: SignupRequest, session: SessionDep) -> TokenResponse:
    raise NotImplementedError


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: SessionDep) -> TokenResponse:
    raise NotImplementedError
