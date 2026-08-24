"""
Attendance data export (Phase 7c). CSV/JSON only - PDF is an untested
extension per API-SPECIFICATION.md's own note (see KNOWN-ISSUES.md),
would need reportlab/weasyprint added to requirements.txt, and isn't
built here.

GET /export/session/{id}'s JSON shape isn't documented anywhere in
API-SPECIFICATION.md (its section just says "returns a downloadable
file") - built to match the one test that covers export
(test_export_session_attendance_json) exactly. GET /export/attendance/
{course_id}'s JSON is documented as a flat array, so that's what it
returns since no test says otherwise - test wins where one exists,
otherwise the doc does.
"""
import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, get_db
from app.core.errors import APIError, ErrorCode
from app.db.models.checkin import CheckIn
from app.db.models.course import Course
from app.db.models.enrollment import Enrollment
from app.db.models.session import ClassSession
from app.db.models.user import User
from app.schemas.export import ExportRecord, SessionExportResponse, SessionExportSummary
from app.services.audit import log_event
from app.services.authz import require_edit_course, require_manage_session

router = APIRouter(prefix="/export", tags=["export"])

CSV_COLUMNS = [
    "student_id", "student_name", "student_email", "session_date", "session_name",
    "status", "checked_in_at", "risk_score",
]
NON_ATTENDANCE_STATUSES = {"rejected"}  # same convention as routers/stats.py


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _checkins_to_records(checkins: List[CheckIn]) -> List[ExportRecord]:
    return [
        ExportRecord(
            student_id=c.student_id, student_name=c.student.full_name, student_email=c.student.email,
            session_date=c.session.scheduled_start.date().isoformat(), session_name=c.session.name,
            status=c.status, checked_in_at=c.checked_in_at, risk_score=c.risk_score,
        )
        for c in checkins
    ]


def _to_csv(records: List[ExportRecord]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for r in records:
        writer.writerow([
            r.student_id, r.student_name, r.student_email, r.session_date, r.session_name,
            r.status, r.checked_in_at.isoformat() if r.checked_in_at else "", r.risk_score,
        ])
    return buf.getvalue()


def _csv_response(csv_text: str, filename: str) -> Response:
    return Response(
        content=csv_text, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/attendance/{course_id}")
def export_course_attendance(
    course_id: str,
    request: Request,
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = db.get(Course, course_id)
    if course is None:
        raise APIError(404, "Course not found", ErrorCode.COURSE_NOT_FOUND)
    require_edit_course(current_user, course)

    query = (
        db.query(CheckIn)
        .join(ClassSession, CheckIn.session_id == ClassSession.id)
        .options(joinedload(CheckIn.student), joinedload(CheckIn.session))
        .filter(ClassSession.course_id == course_id)
    )
    if start_date:
        query = query.filter(CheckIn.checked_in_at >= start_date)
    if end_date:
        query = query.filter(CheckIn.checked_in_at <= end_date)
    checkins = query.order_by(CheckIn.checked_in_at.asc()).all()
    records = _checkins_to_records(checkins)

    log_event(
        db, "data_exported", user_id=current_user.id, resource_type="course", resource_id=course.id,
        ip_address=_client_ip(request), details={"format": format, "record_count": len(records)},
    )
    db.commit()

    if format == "csv":
        return _csv_response(_to_csv(records), f"attendance_{course.code}.csv")
    return records


@router.get("/session/{session_id}", response_model=None)
def export_session_attendance(
    session_id: str,
    request: Request,
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session_obj = db.query(ClassSession).filter(ClassSession.id == session_id).first()
    if session_obj is None:
        raise APIError(404, "Session not found", ErrorCode.SESSION_NOT_FOUND)
    require_manage_session(db, current_user, session_obj)

    total_enrolled = (
        db.query(Enrollment)
        .filter(Enrollment.course_id == session_obj.course_id, Enrollment.is_active.is_(True))
        .count()
    )
    checkins = (
        db.query(CheckIn)
        .options(joinedload(CheckIn.student), joinedload(CheckIn.session))
        .filter(CheckIn.session_id == session_id)
        .order_by(CheckIn.checked_in_at.asc())
        .all()
    )
    records = _checkins_to_records(checkins)

    log_event(
        db, "data_exported", user_id=current_user.id, resource_type="session", resource_id=session_obj.id,
        ip_address=_client_ip(request), details={"format": format, "record_count": len(records)},
    )
    db.commit()

    if format == "csv":
        return _csv_response(_to_csv(records), f"session_{session_obj.name}.csv")

    attended = [c for c in checkins if c.status not in NON_ATTENDANCE_STATUSES]
    approved = [c for c in checkins if c.status == "approved"]
    flagged = [c for c in checkins if c.status == "flagged"]
    avg_risk = round(sum(c.risk_score for c in checkins) / len(checkins), 4) if checkins else 0.0

    return SessionExportResponse(
        session_id=session_obj.id, session_name=session_obj.name,
        summary=SessionExportSummary(
            total_enrolled=total_enrolled, checked_in_count=len(checkins),
            attendance_rate=round(len(attended) / total_enrolled, 4) if total_enrolled else 0.0,
            approved_count=len(approved), flagged_count=len(flagged), average_risk_score=avg_risk,
        ),
        records=records,
    )
