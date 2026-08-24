"""
Session CRUD - see API-SPECIFICATION.md's "Sessions" section and
IMPLEMENTATION-PLAN.md's Phase 4.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, get_db, require_role
from app.core.errors import APIError, ErrorCode
from app.db.models.checkin import CheckIn
from app.db.models.course import Course
from app.db.models.enrollment import Enrollment
from app.db.models.session import ClassSession
from app.db.models.user import User
from app.schemas.common import Page
from app.schemas.session import SessionCreate, SessionResponse, SessionUpdate
from app.services.audit import log_event
from app.services.authz import require_edit_course, require_manage_session
from app.services.sanitize import sanitize_text

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_response(db: Session, session_obj: ClassSession, course: Optional[Course] = None) -> SessionResponse:
    course = course or session_obj.course
    # Two count queries per session - acceptable for now (small course
    # rosters in this project); revisit with a batched aggregate join if
    # Phase 7 perf hardening flags this list endpoint as an N+1 hotspot.
    total_enrolled = (
        db.query(Enrollment)
        .filter(Enrollment.course_id == session_obj.course_id, Enrollment.is_active.is_(True))
        .count()
    )
    checked_in_count = db.query(CheckIn).filter(CheckIn.session_id == session_obj.id).count()
    return SessionResponse(
        id=session_obj.id,
        course_id=session_obj.course_id,
        course_code=course.code if course else None,
        course_name=course.name if course else None,
        instructor_id=session_obj.instructor_id,
        name=session_obj.name,
        session_type=session_obj.session_type,
        description=session_obj.description,
        status=session_obj.status,
        scheduled_start=session_obj.scheduled_start,
        scheduled_end=session_obj.scheduled_end,
        checkin_opens_at=session_obj.checkin_opens_at,
        checkin_closes_at=session_obj.checkin_closes_at,
        actual_start=session_obj.actual_start,
        actual_end=session_obj.actual_end,
        venue_latitude=session_obj.venue_latitude,
        venue_longitude=session_obj.venue_longitude,
        venue_name=session_obj.venue_name,
        geofence_radius_meters=session_obj.geofence_radius_meters,
        require_liveness_check=session_obj.require_liveness_check,
        require_face_match=session_obj.require_face_match,
        risk_threshold=session_obj.risk_threshold,
        qr_code_enabled=session_obj.qr_code_secret is not None,
        total_enrolled=total_enrolled,
        checked_in_count=checked_in_count,
        created_at=session_obj.created_at,
    )


def _validate_schedule(scheduled_start: datetime, scheduled_end: datetime, opens: datetime, closes: datetime) -> None:
    if scheduled_end <= scheduled_start:
        raise APIError(status.HTTP_400_BAD_REQUEST, "scheduled_end must be after scheduled_start", ErrorCode.INVALID_SCHEDULE)
    if closes <= opens:
        raise APIError(status.HTTP_400_BAD_REQUEST, "checkin_closes_at must be after checkin_opens_at", ErrorCode.INVALID_SCHEDULE)


@router.get("/", response_model=Page[SessionResponse])
def list_sessions(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    course_id: Optional[str] = None,
    instructor_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role("instructor", "ta", "admin")),
    db: Session = Depends(get_db),
):
    query = db.query(ClassSession).options(joinedload(ClassSession.course))
    if status_filter:
        query = query.filter(ClassSession.status == status_filter)
    if course_id:
        query = query.filter(ClassSession.course_id == course_id)
    if instructor_id:
        query = query.filter(ClassSession.instructor_id == instructor_id)
    if start_date:
        query = query.filter(ClassSession.scheduled_start >= start_date)
    if end_date:
        query = query.filter(ClassSession.scheduled_start <= end_date)

    total = query.count()
    sessions = query.order_by(ClassSession.scheduled_start.desc()).offset(offset).limit(limit).all()
    return Page(items=[_to_response(db, s) for s in sessions], total=total, limit=limit, offset=offset)


@router.get("/active", response_model=List[SessionResponse])
def list_active_sessions(db: Session = Depends(get_db)):
    now = _now()
    sessions = (
        db.query(ClassSession)
        .options(joinedload(ClassSession.course))
        .filter(
            ClassSession.status == "active",
            ClassSession.checkin_opens_at <= now,
            ClassSession.checkin_closes_at >= now,
        )
        .all()
    )
    return [_to_response(db, s) for s in sessions]


@router.get("/my-sessions", response_model=List[SessionResponse])
def list_my_sessions(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    upcoming: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ClassSession).options(joinedload(ClassSession.course))

    if current_user.role == "student":
        course_ids = [
            row[0]
            for row in db.query(Enrollment.course_id)
            .filter(Enrollment.student_id == current_user.id, Enrollment.is_active.is_(True))
            .all()
        ]
        query = query.filter(ClassSession.course_id.in_(course_ids)) if course_ids else query.filter(False)
    elif current_user.role in ("instructor", "ta"):
        # Covers both: sessions this user is the denormalized owner of
        # (instructor), and sessions for courses this user has an
        # enrollments row in (the ta-scoping convention - see authz.py).
        course_ids = [
            row[0]
            for row in db.query(Enrollment.course_id)
            .filter(Enrollment.student_id == current_user.id, Enrollment.is_active.is_(True))
            .all()
        ]
        query = query.filter(
            (ClassSession.instructor_id == current_user.id) | (ClassSession.course_id.in_(course_ids or [""]))
        )
    # admin: no filter, sees everything

    if status_filter:
        query = query.filter(ClassSession.status == status_filter)
    if upcoming:
        query = query.filter(ClassSession.scheduled_start >= _now())

    sessions = query.order_by(ClassSession.scheduled_start.asc()).limit(limit).all()
    return [_to_response(db, s) for s in sessions]


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session_obj = (
        db.query(ClassSession).options(joinedload(ClassSession.course)).filter(ClassSession.id == session_id).first()
    )
    if session_obj is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Session not found", ErrorCode.SESSION_NOT_FOUND)
    return _to_response(db, session_obj)


@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreate,
    current_user: User = Depends(require_role("instructor", "admin")),
    db: Session = Depends(get_db),
):
    course = db.get(Course, payload.course_id)
    if course is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Course not found", ErrorCode.COURSE_NOT_FOUND)
    require_edit_course(current_user, course)

    checkin_opens_at = payload.checkin_opens_at or (payload.scheduled_start - timedelta(minutes=15))
    checkin_closes_at = payload.checkin_closes_at or (payload.scheduled_start + timedelta(minutes=30))
    _validate_schedule(payload.scheduled_start, payload.scheduled_end, checkin_opens_at, checkin_closes_at)

    session_obj = ClassSession(
        course_id=course.id,
        instructor_id=current_user.id,
        name=payload.name,
        session_type=payload.session_type,
        description=sanitize_text(payload.description) if payload.description else None,
        scheduled_start=payload.scheduled_start,
        scheduled_end=payload.scheduled_end,
        checkin_opens_at=checkin_opens_at,
        checkin_closes_at=checkin_closes_at,
        venue_latitude=payload.venue_latitude,
        venue_longitude=payload.venue_longitude,
        venue_name=payload.venue_name,
        geofence_radius_meters=payload.geofence_radius_meters,
        require_liveness_check=payload.require_liveness_check,
        require_face_match=payload.require_face_match,
        risk_threshold=payload.risk_threshold,
    )
    db.add(session_obj)
    db.flush()
    log_event(
        db, "session_created", user_id=current_user.id, resource_type="session", resource_id=session_obj.id,
        details={"course_id": course.id},
    )
    db.commit()
    db.refresh(session_obj)
    return _to_response(db, session_obj, course=course)


@router.patch("/{session_id}", response_model=SessionResponse)
def update_session(
    session_id: str,
    payload: SessionUpdate,
    current_user: User = Depends(require_role("instructor", "admin")),
    db: Session = Depends(get_db),
):
    session_obj = db.query(ClassSession).filter(ClassSession.id == session_id).first()
    if session_obj is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Session not found", ErrorCode.SESSION_NOT_FOUND)
    require_manage_session(db, current_user, session_obj)

    updates = payload.model_dump(exclude_unset=True)
    if updates.get("description"):
        updates["description"] = sanitize_text(updates["description"])

    new_status = updates.get("status")
    for field, value in updates.items():
        setattr(session_obj, field, value)
    # Stamp actual_start/actual_end on the transitions they correspond to
    # (columns exist for exactly this per DATABASE-SCHEMA.md).
    if new_status == "active" and session_obj.actual_start is None:
        session_obj.actual_start = _now()
    if new_status == "closed" and session_obj.actual_end is None:
        session_obj.actual_end = _now()

    _validate_schedule(
        session_obj.scheduled_start, session_obj.scheduled_end, session_obj.checkin_opens_at, session_obj.checkin_closes_at
    )

    log_event(
        db, "session_updated", user_id=current_user.id, resource_type="session", resource_id=session_obj.id,
        details=updates,
    )
    db.commit()
    db.refresh(session_obj)
    return _to_response(db, session_obj)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    current_user: User = Depends(require_role("instructor", "admin")),
    db: Session = Depends(get_db),
):
    session_obj = db.query(ClassSession).filter(ClassSession.id == session_id).first()
    if session_obj is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Session not found", ErrorCode.SESSION_NOT_FOUND)
    require_manage_session(db, current_user, session_obj)

    if session_obj.status != "scheduled":
        raise APIError(
            status.HTTP_400_BAD_REQUEST, "Only scheduled sessions can be deleted", ErrorCode.SESSION_NOT_DELETABLE
        )

    log_event(db, "session_deleted", user_id=current_user.id, resource_type="session", resource_id=session_obj.id)
    db.delete(session_obj)
    db.commit()
