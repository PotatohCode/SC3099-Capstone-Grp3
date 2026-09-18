from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import Role


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

    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    camera_consent: Optional[bool] = None
    geolocation_consent: Optional[bool] = None


class UserAdminUpdate(BaseModel):
    """PATCH /users/{user_id} - admin only. Role reassignment + soft-delete toggle."""

    role: Optional[Role] = None
    is_active: Optional[bool] = None


class FaceEnrollRequest(BaseModel):
    """POST /users/me/face/enroll. image: base64 PNG/JPEG, no data URL prefix."""

    image: str = Field(min_length=1)


class FaceEnrollResponse(BaseModel):
    success: bool
    message: str
    face_enrolled: bool
    quality_score: float
