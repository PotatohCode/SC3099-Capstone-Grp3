"""Who counts as a course's students.

TAs are attached to a course with an `enrollments` row (that's how
services/authz.py and routers/stats.py scope TA access), so "active
enrollments" alone counts them as students: a course with an assigned TA
showed one extra student at 0% attendance in stats, session counts and
exports. Every student count or list goes through here instead.

Access checks keep querying `enrollments` directly - TAs must still match
there.
"""
from sqlalchemy.orm import Query, Session

from app.db.models.enrollment import Enrollment
from app.db.models.user import User


def active_student_enrollments(db: Session) -> Query:
    """Active enrollments whose user is a student. Callers add their own
    course filter, count or entities on top."""
    return (
        db.query(Enrollment)
        .join(User, Enrollment.student_id == User.id)
        .filter(Enrollment.is_active.is_(True), User.role == "student")
    )
