from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr


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


class MyEnrollmentItem(BaseModel):
    """GET /enrollments/my-enrollments item."""

    id: str
    course_id: str
    course_code: str
    course_name: str
    semester: str
    instructor_name: Optional[str] = None
    enrolled_at: datetime
    is_active: bool


class CourseEnrollmentStudent(BaseModel):
    """One row in GET /enrollments/course/{course_id}'s `students` list."""

    id: str  # enrollment id
    student_id: str
    student_email: str
    student_name: str
    enrolled_at: datetime
    is_active: bool
    face_enrolled: bool


class CourseEnrollmentsResponse(BaseModel):
    course_id: str
    course_code: str
    total_enrolled: int
    students: List[CourseEnrollmentStudent]


class EnrollmentBulkRequest(BaseModel):
    course_id: str
    student_emails: List[EmailStr]
    create_accounts: bool = False


class EnrollmentBulkDetailItem(BaseModel):
    email: str
    status: str  # "enrolled" | "already_enrolled" | "not_found"


class EnrollmentBulkResponse(BaseModel):
    enrolled: int
    already_enrolled: int
    not_found: int
    created: int
    details: List[EnrollmentBulkDetailItem]
