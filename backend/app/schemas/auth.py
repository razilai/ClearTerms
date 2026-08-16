from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field, SecretStr

from app.core.config import settings

# Normalized at the boundary so lookups and the stored email are always
# lowercase. Login arrives via OAuth2 form data (no schema), so services
# lowercase again as the enforced invariant.
LowercaseEmail = Annotated[EmailStr, AfterValidator(str.lower)]


class SignupRequest(BaseModel):
    email: LowercaseEmail = Field(max_length=settings.max_email_chars)
    # The upper bound is not a policy on password strength — it stops one
    # request from making argon2 hash an unbounded blob. Login enforces the
    # same two caps by hand (app.services.auth.login): it arrives as OAuth2
    # form data, so no schema runs on it.
    password: SecretStr = Field(min_length=8, max_length=settings.max_password_chars)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: int  # the JWT carries it as a string; pydantic coerces it back
    iat: datetime
    exp: datetime
