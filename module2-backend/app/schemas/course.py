from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CourseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=255)
    semester: str = Field(min_length=1, max_length=20)
    description: Optional[str] = None
    instructor_id: Optional[str] = None
    venue_name: Optional[str] = None
    venue_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    venue_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    geofence_radius_meters: float = 100.0
    require_face_recognition: bool = False
    require_device_binding: bool = True
    risk_threshold: float = Field(default=0.5, ge=0, le=1)


class CourseUpdate(BaseModel):
    """PUT /courses/{course_id} - all fields optional, partial update."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    semester: Optional[str] = Field(default=None, min_length=1, max_length=20)
    instructor_id: Optional[str] = None
    venue_name: Optional[str] = None
    venue_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    venue_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    geofence_radius_meters: Optional[float] = None
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
