"""
Student-facing enrollment endpoints - see API-SPECIFICATION.md's
"Enrollments" section. The admin bypass-ownership variant lives in
routers/admin.py (POST /admin/enrollments/).
"""
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, get_db, require_role
from app.core.errors import APIError, ErrorCode
from app.core.security import get_password_hash
from app.db.models.course import Course
from app.db.models.enrollment import Enrollment
from app.db.models.user import User
from app.schemas.enrollment import (
    CourseEnrollmentsResponse,
    CourseEnrollmentStudent,
    EnrollmentBulkDetailItem,
    EnrollmentBulkRequest,
    EnrollmentBulkResponse,
    EnrollmentCreate,
    EnrollmentResponse,
    MyEnrollmentItem,
)
from app.services.audit import log_event
from app.services.authz import require_edit_course, require_staff_course

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@router.get("/my-enrollments", response_model=List[MyEnrollmentItem])
def my_enrollments(
    current_user: User = Depends(require_role("student")),
    db: Session = Depends(get_db),
):
    enrollments = (
        db.query(Enrollment)
        .options(joinedload(Enrollment.course).joinedload(Course.instructor))
        .filter(Enrollment.student_id == current_user.id, Enrollment.is_active.is_(True))
        .all()
    )
    return [
        MyEnrollmentItem(
            id=e.id,
            course_id=e.course_id,
            course_code=e.course.code,
            course_name=e.course.name,
            semester=e.course.semester,
            instructor_name=e.course.instructor.full_name if e.course.instructor else None,
            enrolled_at=e.enrolled_at,
            is_active=e.is_active,
        )
        for e in enrollments
    ]


@router.get("/course/{course_id}", response_model=CourseEnrollmentsResponse)
def course_enrollments(
    course_id: str,
    is_active: bool = True,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = db.get(Course, course_id)
    if course is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Course not found", ErrorCode.COURSE_NOT_FOUND)
    require_staff_course(db, current_user, course)

    query = (
        db.query(Enrollment)
        .join(User, Enrollment.student_id == User.id)
        .options(joinedload(Enrollment.student))
        .filter(Enrollment.course_id == course_id, Enrollment.is_active.is_(is_active))
    )
    if search:
        like = f"%{search}%"
        query = query.filter((User.full_name.ilike(like)) | (User.email.ilike(like)))
    enrollments = query.all()

    return CourseEnrollmentsResponse(
        course_id=course.id,
        course_code=course.code,
        total_enrolled=len(enrollments),
        students=[
            CourseEnrollmentStudent(
                id=e.id,
                student_id=e.student_id,
                student_email=e.student.email,
                student_name=e.student.full_name,
                enrolled_at=e.enrolled_at,
                is_active=e.is_active,
                face_enrolled=e.student.face_enrolled,
            )
            for e in enrollments
        ],
    )


@router.post("/", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED)
def create_enrollment(
    payload: EnrollmentCreate,
    current_user: User = Depends(require_role("instructor", "admin")),
    db: Session = Depends(get_db),
):
    course = db.get(Course, payload.course_id)
    if course is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Course not found", ErrorCode.COURSE_NOT_FOUND)
    require_edit_course(current_user, course)

    if db.get(User, payload.student_id) is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Student not found", ErrorCode.STUDENT_NOT_FOUND)

    existing = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == payload.student_id, Enrollment.course_id == payload.course_id)
        .first()
    )
    if existing is not None:
        raise APIError(status.HTTP_400_BAD_REQUEST, "Student already enrolled", ErrorCode.ALREADY_ENROLLED)

    enrollment = Enrollment(student_id=payload.student_id, course_id=payload.course_id)
    db.add(enrollment)
    db.flush()
    log_event(
        db, "enrollment_added", user_id=current_user.id, resource_type="enrollment", resource_id=enrollment.id,
        details={"student_id": payload.student_id, "course_id": payload.course_id},
    )
    db.commit()
    db.refresh(enrollment)
    return enrollment


@router.post("/bulk", response_model=EnrollmentBulkResponse)
def bulk_enroll(
    payload: EnrollmentBulkRequest,
    current_user: User = Depends(require_role("instructor", "admin")),
    db: Session = Depends(get_db),
):
    course = db.get(Course, payload.course_id)
    if course is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Course not found", ErrorCode.COURSE_NOT_FOUND)
    require_edit_course(current_user, course)

    enrolled = already_enrolled = not_found = created = 0
    details: List[EnrollmentBulkDetailItem] = []

    for email in payload.student_emails:
        student = db.query(User).filter(User.email == email).first()

        if student is None:
            if not payload.create_accounts:
                not_found += 1
                details.append(EnrollmentBulkDetailItem(email=email, status="not_found"))
                continue
            student = User(
                email=email,
                full_name=email.split("@")[0],
                # Random password: this account only exists because a
                # roster import referenced it - the real student resets
                # their password via a normal flow before ever logging in.
                hashed_password=get_password_hash(secrets.token_urlsafe(16)),
                role="student",
            )
            db.add(student)
            db.flush()
            log_event(db, "user_created", user_id=student.id, resource_type="user", resource_id=student.id)
            created += 1

        existing = (
            db.query(Enrollment)
            .filter(Enrollment.student_id == student.id, Enrollment.course_id == payload.course_id)
            .first()
        )
        if existing is not None:
            already_enrolled += 1
            details.append(EnrollmentBulkDetailItem(email=email, status="already_enrolled"))
            continue

        enrollment = Enrollment(student_id=student.id, course_id=payload.course_id)
        db.add(enrollment)
        db.flush()
        log_event(
            db, "enrollment_added", user_id=current_user.id, resource_type="enrollment", resource_id=enrollment.id,
            details={"student_id": student.id, "course_id": payload.course_id, "via": "bulk"},
        )
        enrolled += 1
        details.append(EnrollmentBulkDetailItem(email=email, status="enrolled"))

    db.commit()
    return EnrollmentBulkResponse(
        enrolled=enrolled, already_enrolled=already_enrolled, not_found=not_found, created=created, details=details
    )


@router.delete("/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_enrollment(
    enrollment_id: str,
    current_user: User = Depends(require_role("instructor", "admin")),
    db: Session = Depends(get_db),
):
    enrollment = db.get(Enrollment, enrollment_id)
    if enrollment is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Enrollment not found", ErrorCode.ENROLLMENT_NOT_FOUND)

    course = db.get(Course, enrollment.course_id)
    require_edit_course(current_user, course)

    enrollment.is_active = False
    enrollment.dropped_at = datetime.now(timezone.utc)
    log_event(db, "enrollment_removed", user_id=current_user.id, resource_type="enrollment", resource_id=enrollment.id)
    db.commit()
