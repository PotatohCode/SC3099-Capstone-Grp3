from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import PASSWORD_MAX_LENGTH, EscapedName, Role
from app.schemas.user import UserResponse


class RegisterRequest(BaseModel):
    email: EmailStr
    # min_length=8 -> Pydantic itself returns 422 for a weak password, per
    # SECURITY-REQUIREMENTS.md's "Return 422 if too weak" (API-SPECIFICATION.md's
    # prose says 400 for this case, but tests/public/test_security_basic.py
    # asserts 422 - tests win per IMPLEMENTATION-PLAN.md's own stated rule).
    # max_length: passlib refuses to hash > 4096 characters (it was a 500),
    # and bcrypt only uses the first 72 bytes anyway. 128 is generous.
    password: str = Field(min_length=8, max_length=PASSWORD_MAX_LENGTH)
    full_name: EscapedName
    # Design deck: "Ignore security restrictions about the roles during
    # registration" - any role, including admin, can self-register.
    role: Role = "student"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LogoutRequest(BaseModel):
    """Body is optional; the access token in the Authorization header (if
    any) is revoked too."""
    refresh_token: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
