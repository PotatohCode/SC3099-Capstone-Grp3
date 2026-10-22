"""Adding a user to a course's roster, shared by POST /enrollments/,
POST /enrollments/bulk and POST /admin/enrollments/.

enrollments has a UNIQUE (student_id, course_id) constraint and removal is
a soft delete (is_active=false), so a removed student's row is still
there. Re-adding them reactivates that row; inserting a second one would
violate the constraint, and refusing ("already enrolled") left them
locked out of the course for good.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models.enrollment import Enrollment
from app.services.audit import log_event


class EnrollOutcome(str, Enum):
    CREATED = "created"
    REACTIVATED = "reactivated"
    ALREADY_ENROLLED = "already_enrolled"


def enroll(
    db: Session, student_id: str, course_id: str, actor_id: str, via: Optional[str] = None
) -> Tuple[Enrollment, EnrollOutcome]:
    """Creates or reactivates the enrollment and writes its audit row.
    Doesn't commit; the caller does. ALREADY_ENROLLED (an active row exists)
    changes nothing."""
    existing = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == student_id, Enrollment.course_id == course_id)
        .first()
    )
    if existing is not None and existing.is_active:
        return existing, EnrollOutcome.ALREADY_ENROLLED

    details = {"student_id": student_id, "course_id": course_id}
    if via:
        details["via"] = via
    if existing is not None:
        existing.is_active = True
        existing.dropped_at = None
        existing.enrolled_at = datetime.now(timezone.utc).replace(tzinfo=None)
        enrollment, outcome = existing, EnrollOutcome.REACTIVATED
        details["reactivated"] = True
    else:
        enrollment = Enrollment(student_id=student_id, course_id=course_id)
        db.add(enrollment)
        db.flush()
        outcome = EnrollOutcome.CREATED

    log_event(
        db, "enrollment_added", user_id=actor_id, resource_type="enrollment", resource_id=enrollment.id,
        details=details,
    )
    return enrollment, outcome
