from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field, SecretStr

# Normalized at the boundary so lookups and the stored email are always
# lowercase. Login arrives via OAuth2 form data (no schema), so services
# lowercase again as the enforced invariant.
LowercaseEmail = Annotated[EmailStr, AfterValidator(str.lower)]


class SignupRequest(BaseModel):
    email: LowercaseEmail
    password: SecretStr = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
