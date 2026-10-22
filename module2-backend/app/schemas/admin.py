from typing import List, Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.auth import Role
from app.schemas.common import PASSWORD_MAX_LENGTH, EscapedName


class AdminUserBulkItem(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=PASSWORD_MAX_LENGTH)
    full_name: EscapedName
    role: Role = "student"


class AdminUserBulkCreate(BaseModel):
    users: List[AdminUserBulkItem]


class AdminUserBulkResultItem(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: str


class AdminUserBulkErrorItem(BaseModel):
    email: str
    error: str


class AdminUserBulkResponse(BaseModel):
    created: int
    failed: int
    users: List[AdminUserBulkResultItem]
    errors: List[AdminUserBulkErrorItem]


class AdminUserStatusResponse(BaseModel):
    id: str
    email: EmailStr
    is_active: bool
    message: str


class AdminSessionStatusUpdate(BaseModel):
    status: Literal["scheduled", "active", "closed", "cancelled"]


class AdminSessionStatusResponse(BaseModel):
    id: str
    name: str
    status: str
    message: str


class RetentionSweepResponse(BaseModel):
    users_anonymized: int
    checkins_anonymized: int
    message: str
