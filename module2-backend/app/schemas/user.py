from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
