from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EnrollmentCreate(BaseModel):
    student_id: str
    course_id: str


class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    course_id: str
    is_active: bool
    enrolled_at: datetime
