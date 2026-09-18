"""
Course/session-scoped RBAC checks, on top of the single global `role`
claim (see core/deps.py's require_role). Per DATABASE-SCHEMA.md, role
never varies per course - only the *set* of courses a request may touch
varies, via courses.instructor_id (ownership) or enrollments (which
courses a ta/student belongs to).
"""
from fastapi import status
from sqlalchemy.orm import Session

from app.core.errors import APIError, ErrorCode
from app.db.models.course import Course
from app.db.models.enrollment import Enrollment
from app.db.models.session import ClassSession
from app.db.models.user import User


def _owns_course(user: User, course: Course) -> bool:
    # A course with no instructor_id assigned yet is manageable by any
    # instructor - tests/conftest.py's test_course fixture creates courses
    # without setting instructor_id, and downstream fixtures (test_session)
    # then act on that course as an arbitrary instructor.
    return course.instructor_id is None or course.instructor_id == user.id


def _owns_session(user: User, session_obj: ClassSession) -> bool:
    return session_obj.instructor_id is None or session_obj.instructor_id == user.id


def _ta_assigned(db: Session, user: User, course_id: str) -> bool:
    """TA course scope = an active enrollments row for the TA's own user id
    in that course. enrollments is a plain user<->course link with no
    per-course role column, so this is the only signal available for
    "which courses is this TA assigned to" per the RBAC design."""
    return (
        db.query(Enrollment)
        .filter(Enrollment.student_id == user.id, Enrollment.course_id == course_id, Enrollment.is_active.is_(True))
        .first()
        is not None
    )


def can_edit_course(user: User, course: Course) -> bool:
    """admin, or the course's own instructor. Used for PUT/DELETE
    /courses and enrollment writes ("instructor for course, or admin" per
    API-SPECIFICATION.md - ta is deliberately excluded here)."""
    if user.role == "admin":
        return True
    return user.role == "instructor" and _owns_course(user, course)


def can_staff_course(db: Session, user: User, course: Course) -> bool:
    """admin, owning instructor, or an assigned ta - read/manage access for
    ta-inclusive endpoints (GET /enrollments/course/{id}, flagged review)."""
    if user.role == "admin":
        return True
    if user.role == "instructor":
        return _owns_course(user, course)
    if user.role == "ta":
        return _ta_assigned(db, user, course.id)
    return False


def can_manage_session(db: Session, user: User, session_obj: ClassSession) -> bool:
    if user.role == "admin":
        return True
    if user.role == "instructor":
        return _owns_session(user, session_obj)
    if user.role == "ta":
        return _ta_assigned(db, user, session_obj.course_id)
    return False


def can_export_course(db: Session, user: User, course: Course) -> bool:
    """Stricter than can_edit_course - for read endpoints that disclose
    real records (currently just export), not write/setup actions.
    admin, or an instructor who owns the course directly (exact
    instructor_id match, no None-leniency), or an instructor who owns at
    least one session under it.

    Found 2026-08-24 (Phase 7c): can_edit_course's "unassigned course is
    manageable by any instructor" leniency let a totally unrelated
    instructor export a course's attendance (names/emails/risk scores)
    purely because nobody had claimed the course - confirmed live. This
    helper closes that gap for export specifically. Deliberately NOT
    folded into can_edit_course itself: POST /enrollments/ and
    POST /sessions/ need an instructor to act on a fresh, unclaimed
    course *before* any session exists (setting up a roster comes before
    scheduling the first lecture) - export doesn't have that problem,
    since there's nothing to export before a session exists anyway. See
    KNOWN-ISSUES.md for the full writeup."""
    if user.role == "admin":
        return True
    if user.role != "instructor":
        return False
    if course.instructor_id == user.id:
        return True
    return (
        db.query(ClassSession)
        .filter(ClassSession.course_id == course.id, ClassSession.instructor_id == user.id)
        .first()
        is not None
    )


def require_export_course(db: Session, user: User, course: Course) -> None:
    if not can_export_course(db, user, course):
        raise APIError(status.HTTP_403_FORBIDDEN, "Not authorized for this course", ErrorCode.INSUFFICIENT_PERMISSIONS)


def require_edit_course(user: User, course: Course) -> None:
    if not can_edit_course(user, course):
        raise APIError(status.HTTP_403_FORBIDDEN, "Not authorized for this course", ErrorCode.INSUFFICIENT_PERMISSIONS)


def require_staff_course(db: Session, user: User, course: Course) -> None:
    if not can_staff_course(db, user, course):
        raise APIError(status.HTTP_403_FORBIDDEN, "Not authorized for this course", ErrorCode.INSUFFICIENT_PERMISSIONS)


def require_manage_session(db: Session, user: User, session_obj: ClassSession) -> None:
    if not can_manage_session(db, user, session_obj):
        raise APIError(status.HTTP_403_FORBIDDEN, "Not authorized for this session", ErrorCode.INSUFFICIENT_PERMISSIONS)
