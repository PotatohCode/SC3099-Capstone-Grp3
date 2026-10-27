from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import PASSWORD_MAX_LENGTH, EscapedName, Role


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str
    role: str
    is_active: bool
    camera_consent: bool
    geolocation_consent: bool
    face_enrolled: bool
    created_at: datetime


class UserUpdateRequest(BaseModel):
    """PUT /users/me - all fields optional, only supplied ones are changed."""

    full_name: Optional[EscapedName] = None
    camera_consent: Optional[bool] = None
    geolocation_consent: Optional[bool] = None


class UserAdminUpdate(BaseModel):
    """PATCH /users/{user_id} - admin only. Role reassignment + soft-delete toggle."""

    role: Optional[Role] = None
    is_active: Optional[bool] = None


class FaceEnrollRequest(BaseModel):
    """POST /users/me/face/enroll. image: base64 PNG/JPEG, no data URL prefix."""

    image: str = Field(min_length=1)
    # Needed only when a face is already enrolled: the one-time code from an
    # instructor (POST /users/{id}/face/reset-code). Case, spaces and
    # hyphens don't matter.
    reset_code: Optional[str] = Field(default=None, max_length=32)


class FaceResetCodeResponse(BaseModel):
    """POST /users/{student_id}/face/reset-code (201). Shown once."""
    student_id: str
    code: str
    expires_at: datetime


class FaceEnrollResponse(BaseModel):
    success: bool
    message: str
    face_enrolled: bool
    quality_score: float


class AccountDeletionRequest(BaseModel):
    """DELETE /users/me: the current password, so a stolen access token
    alone can't delete an account."""
    password: str = Field(min_length=1)


class PasswordChangeRequest(BaseModel):
    """POST /users/me/password. new_password follows RegisterRequest's rules
    (422 if too short or too long)."""
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(min_length=8, max_length=PASSWORD_MAX_LENGTH)


class AccountDeletionResponse(BaseModel):
    message: str
    scheduled_deletion_at: datetime
