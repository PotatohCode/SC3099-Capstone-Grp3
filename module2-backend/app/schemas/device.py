from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Platform = Literal["ios", "android", "web", "desktop"]


class DeviceRegisterRequest(BaseModel):
    device_fingerprint: str = Field(min_length=1, max_length=64)
    device_name: Optional[str] = Field(default=None, max_length=255)
    platform: Optional[Platform] = None
    browser: Optional[str] = Field(default=None, max_length=100)
    os_version: Optional[str] = Field(default=None, max_length=50)
    app_version: Optional[str] = Field(default=None, max_length=50)
    # NOT in DATABASE-SCHEMA.md's NOT NULL - tests/conftest.py's test_device
    # fixture registers without one, so it must be optional here too.
    public_key: Optional[str] = None


class DeviceUpdateRequest(BaseModel):
    """PATCH /devices/{device_id} - device_name/is_active: owner or admin.
    is_trusted: admin only, silently ignored (not rejected) for a
    non-admin caller - same pattern as courses' instructor_id filter."""

    device_name: Optional[str] = Field(default=None, max_length=255)
    is_active: Optional[bool] = None
    is_trusted: Optional[bool] = None


class DeviceResponse(BaseModel):
    id: str
    device_fingerprint: str
    device_name: Optional[str] = None
    platform: Optional[str] = None
    browser: Optional[str] = None
    os_version: Optional[str] = None
    app_version: Optional[str] = None
    is_trusted: bool
    trust_score: str
    is_active: bool
    total_checkins: int
    first_seen_at: datetime
    last_seen_at: datetime
