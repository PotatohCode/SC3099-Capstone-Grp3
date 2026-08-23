from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserResponse

Role = Literal["student", "instructor", "ta", "admin"]


class RegisterRequest(BaseModel):
    email: EmailStr
    # min_length=8 -> Pydantic itself returns 422 for a weak password, per
    # SECURITY-REQUIREMENTS.md's "Return 422 if too weak" (API-SPECIFICATION.md's
    # prose says 400 for this case, but tests/public/test_security_basic.py
    # asserts 422 - tests win per IMPLEMENTATION-PLAN.md's own stated rule).
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, max_length=255)
    # Design deck: "Ignore security restrictions about the roles during
    # registration" - any role, including admin, can self-register.
    role: Role = "student"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


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
