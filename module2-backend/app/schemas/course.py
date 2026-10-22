from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import EscapedLabel, EscapedName

# Course codes are identifiers (CS101, SC3099): letters, digits, spaces, "-"
# and "_" only. Rejected (422) rather than escaped: the code is used for the
# duplicate check, lookups and the export filename.
COURSE_CODE_PATTERN = r"^[A-Za-z0-9 _-]+$"


class CourseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20, pattern=COURSE_CODE_PATTERN)
    name: EscapedName
    semester: str = Field(min_length=1, max_length=20)
    description: Optional[str] = None
    instructor_id: Optional[str] = None
    venue_name: Optional[EscapedLabel] = None
    venue_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    venue_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    geofence_radius_meters: float = Field(default=100.0, gt=0)
    require_face_recognition: bool = False
    require_device_binding: bool = True
    risk_threshold: float = Field(default=0.5, ge=0, le=1)


class CourseUpdate(BaseModel):
    """PUT /courses/{course_id} - all fields optional, partial update."""

    name: Optional[EscapedName] = None
    description: Optional[str] = None
    semester: Optional[str] = Field(default=None, min_length=1, max_length=20)
    instructor_id: Optional[str] = None
    venue_name: Optional[EscapedLabel] = None
    venue_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    venue_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    geofence_radius_meters: Optional[float] = Field(default=None, gt=0)
    require_face_recognition: Optional[bool] = None
    require_device_binding: Optional[bool] = None
    risk_threshold: Optional[float] = Field(default=None, ge=0, le=1)
    is_active: Optional[bool] = None


class CourseResponse(BaseModel):
    id: str
    code: str
    name: str
    description: Optional[str] = None
    semester: str
    instructor_id: Optional[str] = None
    instructor_name: Optional[str] = None
    venue_name: Optional[str] = None
    venue_latitude: Optional[float] = None
    venue_longitude: Optional[float] = None
    geofence_radius_meters: float
    require_face_recognition: bool
    require_device_binding: bool
    risk_threshold: float
    is_active: bool
    created_at: datetime
