from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

SessionType = Literal["lecture", "tutorial", "lab", "exam"]
SessionStatusLiteral = Literal["scheduled", "active", "closed", "cancelled"]


class SessionCreate(BaseModel):
    course_id: str
    name: str = Field(min_length=1, max_length=255)
    session_type: SessionType = "lecture"
    description: Optional[str] = None
    scheduled_start: datetime
    scheduled_end: datetime
    # Both optional - default to 15min before / 30min after scheduled_start
    # per API-SPECIFICATION.md's POST /sessions/ request comments.
    checkin_opens_at: Optional[datetime] = None
    checkin_closes_at: Optional[datetime] = None
    venue_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    venue_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    venue_name: Optional[str] = None
    geofence_radius_meters: Optional[float] = None
    require_liveness_check: bool = True
    require_face_match: bool = False
    risk_threshold: Optional[float] = Field(default=None, ge=0, le=1)


class SessionUpdate(BaseModel):
    """PATCH /sessions/{session_id} - partial update, any subset of fields."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    session_type: Optional[SessionType] = None
    description: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    checkin_opens_at: Optional[datetime] = None
    checkin_closes_at: Optional[datetime] = None
    status: Optional[SessionStatusLiteral] = None
    venue_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    venue_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    venue_name: Optional[str] = None
    geofence_radius_meters: Optional[float] = None
    require_liveness_check: Optional[bool] = None
    require_face_match: Optional[bool] = None
    risk_threshold: Optional[float] = Field(default=None, ge=0, le=1)


class SessionResponse(BaseModel):
    id: str
    course_id: str
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    instructor_id: Optional[str] = None
    name: str
    session_type: str
    description: Optional[str] = None
    status: str
    scheduled_start: datetime
    scheduled_end: datetime
    checkin_opens_at: datetime
    checkin_closes_at: datetime
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    venue_latitude: Optional[float] = None
    venue_longitude: Optional[float] = None
    venue_name: Optional[str] = None
    geofence_radius_meters: Optional[float] = None
    require_liveness_check: bool
    require_face_match: bool
    risk_threshold: Optional[float] = None
    qr_code_enabled: bool = False
    total_enrolled: Optional[int] = None
    checked_in_count: Optional[int] = None
    created_at: datetime
