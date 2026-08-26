"""
Check-in submission, review, and query endpoints (Task 2.7). The core
pipeline (geofencing, risk scoring, Face Service calls) lives in
services/geofencing.py, services/risk_scoring.py, services/face_client.py -
this router stays thin per IMPLEMENTATION-PLAN.md's own rule.

See KNOWN-ISSUES.md before touching the decision logic: the hard override
(liveness explicitly failed, or GPS > 2x geofence radius -> rejected
regardless of score) is not a pure `risk_score < threshold` comparison,
and Module 3 is currently a 501 stub so the degrade-gracefully paths are
what actually run end-to-end today.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.deps import get_current_user, get_db, require_role
from app.core.errors import APIError, ErrorCode
from app.core.metrics import checkin_attempts_total, checkin_success_total, checkins_flagged_total, risk_score_histogram
from app.db.models.checkin import CheckIn
from app.db.models.device import Device
from app.db.models.enrollment import Enrollment
from app.db.models.risk_signal import RiskSignal
from app.db.models.session import ClassSession
from app.db.models.user import User
from app.schemas.checkin import (
    CheckinAppealRequest,
    CheckinAppealResponse,
    CheckinCreate,
    CheckinListItem,
    CheckinResponse,
    CheckinReviewRequest,
    CheckinReviewResponse,
    FlaggedCheckinItem,
    FlaggedCheckinRiskFactor,
    MyCheckinItem,
    RiskFactorItem,
    SessionCheckinItem,
)
from app.schemas.common import Page
from app.services import face_client, geofencing, risk_scoring
from app.services.audit import log_event
from app.services.authz import can_manage_session, require_manage_session
from app.services.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/checkins", tags=["checkins"])
settings = get_settings()

APPEAL_WINDOW_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _parse_risk_factors(raw: Optional[str]) -> List[RiskFactorItem]:
    if not raw:
        return []
    try:
        return [RiskFactorItem(**item) for item in json.loads(raw)]
    except (ValueError, TypeError):
        return []


def _to_full_response(checkin: CheckIn) -> CheckinResponse:
    return CheckinResponse(
        id=checkin.id,
        session_id=checkin.session_id,
        student_id=checkin.student_id,
        device_id=checkin.device_id,
        status=checkin.status,
        checked_in_at=checkin.checked_in_at,
        verified_at=checkin.verified_at,
        latitude=checkin.latitude,
        longitude=checkin.longitude,
        location_accuracy_meters=checkin.location_accuracy_meters,
        distance_from_venue_meters=checkin.distance_from_venue_meters,
        liveness_passed=checkin.liveness_passed,
        liveness_score=checkin.liveness_score,
        face_match_passed=checkin.face_match_passed,
        face_match_score=checkin.face_match_score,
        face_embedding_hash=checkin.face_embedding_hash,
        risk_score=checkin.risk_score,
        risk_factors=_parse_risk_factors(checkin.risk_factors),
        qr_code_verified=checkin.qr_code_verified,
        reviewed_by_id=checkin.reviewed_by_id,
        reviewed_at=checkin.reviewed_at,
        review_notes=checkin.review_notes,
        appeal_reason=checkin.appeal_reason,
        appealed_at=checkin.appealed_at,
    )


def _scope_sessions_for_staff(db: Session, user: User):
    """Filter condition scoping ClassSession rows to what this
    instructor/ta can manage - None for admin (no scoping needed)."""
    if user.role == "admin":
        return None
    course_ids = [
        row[0]
        for row in db.query(Enrollment.course_id)
        .filter(Enrollment.student_id == user.id, Enrollment.is_active.is_(True))
        .all()
    ]
    return (ClassSession.instructor_id == user.id) | (ClassSession.course_id.in_(course_ids or [""]))


# =============================================================================
# POST /checkins/
# =============================================================================

@router.post("/", response_model=CheckinResponse, status_code=status.HTTP_201_CREATED)
def create_checkin(
    payload: CheckinCreate,
    request: Request,
    current_user: User = Depends(require_role("student")),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(f"rate_limit:{current_user.id}:checkin", settings.RATE_LIMIT_CHECKIN_PER_MINUTE, 60)
    checkin_attempts_total.inc()

    session_obj = (
        db.query(ClassSession).options(joinedload(ClassSession.course)).filter(ClassSession.id == payload.session_id).first()
    )
    if session_obj is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Session not found", ErrorCode.SESSION_NOT_FOUND)
    course = session_obj.course

    is_enrolled = (
        db.query(Enrollment)
        .filter(
            Enrollment.student_id == current_user.id, Enrollment.course_id == course.id, Enrollment.is_active.is_(True)
        )
        .first()
        is not None
    )
    if not is_enrolled:
        raise APIError(status.HTTP_403_FORBIDDEN, "Not enrolled in this course", ErrorCode.NOT_ENROLLED)

    if session_obj.status != "active":
        raise APIError(status.HTTP_400_BAD_REQUEST, "Session is not active", ErrorCode.SESSION_NOT_ACTIVE)

    now = _now()
    if not (session_obj.checkin_opens_at <= now <= session_obj.checkin_closes_at):
        raise APIError(status.HTTP_400_BAD_REQUEST, "Check-in window is closed", ErrorCode.SESSION_WINDOW_CLOSED)

    existing = (
        db.query(CheckIn)
        .filter(CheckIn.session_id == session_obj.id, CheckIn.student_id == current_user.id)
        .first()
    )
    if existing is not None:
        raise APIError(status.HTTP_400_BAD_REQUEST, "Already checked in for this session", ErrorCode.ALREADY_CHECKED_IN)

    # --- Device resolution -------------------------------------------------
    device = (
        db.query(Device)
        .filter(Device.device_fingerprint == payload.device_fingerprint, Device.user_id == current_user.id)
        .first()
    )
    device_known = device is not None
    device_trusted = device.is_trusted if device else None

    # --- Geofencing ----------------------------------------------------------
    venue_lat, venue_lon, radius = geofencing.effective_venue(session_obj, course)
    distance = (
        geofencing.distance_meters(payload.latitude, payload.longitude, venue_lat, venue_lon)
        if venue_lat is not None and venue_lon is not None
        else None
    )

    # --- Liveness + face match (defensive: 5s timeout, degrade on failure) --
    liveness_passed: Optional[bool] = None
    liveness_score = 0.0
    face_match_passed: Optional[bool] = None
    face_match_score: Optional[float] = None
    current_face_hash: Optional[str] = None

    if payload.liveness_challenge_response:
        liveness_result = face_client.check_liveness(payload.liveness_challenge_response)
        if liveness_result is not None:
            liveness_passed = liveness_result.get("liveness_passed")
            liveness_score = liveness_result.get("liveness_score", 0.0) or 0.0

        if current_user.face_embedding_hash:
            verify_result = face_client.verify_face(payload.liveness_challenge_response, current_user.face_embedding_hash)
            if verify_result is not None:
                face_match_passed = verify_result.get("match_passed")
                face_match_score = verify_result.get("match_score")
                current_face_hash = verify_result.get("current_template_hash")

    # --- Risk scoring: prefer Module 3's /risk/assess, else local fallback --
    # Only worth the round-trip if we actually have image-derived signals
    # to send - with neither, 3 of Module 3's 5 weighted signals (liveness,
    # face_match, and effectively device) would be blank anyway, and the
    # geo signal is already computed independently via geofencing above.
    remote_risk = None
    if payload.liveness_challenge_response:
        remote_risk = face_client.assess_risk({
            "liveness_score": liveness_score,
            "face_match_score": face_match_score,
            "user_agent": request.headers.get("user-agent"),
            "ip_address": _client_ip(request),
            "geolocation": {
                "latitude": payload.latitude, "longitude": payload.longitude, "accuracy": payload.location_accuracy_meters,
            },
        })
    if remote_risk is not None and "risk_score" in remote_risk:
        base_score = float(remote_risk["risk_score"])
    else:
        distance_ratio = (distance / radius) if (distance is not None and radius) else None
        base_score = risk_scoring.compute_fallback_risk(liveness_score, distance_ratio, device_trusted)

    # --- Impossible-travel check against the student's previous check-in ----
    previous = (
        db.query(CheckIn)
        .filter(CheckIn.student_id == current_user.id)
        .order_by(CheckIn.checked_in_at.desc())
        .first()
    )
    previous_distance_meters = None
    if previous is not None and previous.latitude is not None and previous.longitude is not None:
        previous_distance_meters = geofencing.distance_meters(
            payload.latitude, payload.longitude, previous.latitude, previous.longitude
        )

    effective_threshold = session_obj.risk_threshold if session_obj.risk_threshold is not None else course.risk_threshold

    assessment = risk_scoring.assess(
        base_risk_score=base_score,
        distance_meters=distance,
        geofence_radius=radius,
        location_accuracy_meters=payload.location_accuracy_meters,
        liveness_passed=liveness_passed,
        device_known=device_known,
        device_trusted=device_trusted,
        previous_checkin_at=previous.checked_in_at if previous else None,
        previous_distance_meters=previous_distance_meters,
        current_checkin_at=now,
        risk_threshold=effective_threshold,
    )

    log_event(
        db, "checkin_attempted", user_id=current_user.id, resource_type="session", resource_id=session_obj.id,
        ip_address=_client_ip(request), user_agent=request.headers.get("user-agent"),
        details={"session_id": session_obj.id, "device_fingerprint": payload.device_fingerprint},
    )

    checkin = CheckIn(
        session_id=session_obj.id,
        student_id=current_user.id,
        device_id=device.id if device else None,
        status=assessment.status,
        checked_in_at=now,
        verified_at=now,
        latitude=payload.latitude,
        longitude=payload.longitude,
        location_accuracy_meters=payload.location_accuracy_meters,
        distance_from_venue_meters=distance,
        liveness_passed=liveness_passed,
        liveness_score=liveness_score,
        liveness_challenge_type="passive" if payload.liveness_challenge_response else None,
        face_match_passed=face_match_passed,
        face_match_score=face_match_score,
        face_embedding_hash=current_face_hash,
        risk_score=assessment.risk_score,
        risk_factors=json.dumps(assessment.risk_factors),
        qr_code_verified=False,  # QR flow not implemented in Phase 6 - see KNOWN-ISSUES.md
        # Phase 7e: PII retention (SECURITY-REQUIREMENTS.md - 30 days for
        # check-in records). Set at creation time since this is a blanket
        # window, not tied to any later action - see services/retention.py.
        scheduled_deletion_at=now + timedelta(days=settings.PII_RETENTION_DAYS),
    )
    db.add(checkin)
    db.flush()

    for signal in assessment.signals:
        db.add(RiskSignal(
            checkin_id=checkin.id, signal_type=signal.signal_type, severity=signal.severity,
            weight=signal.weight, confidence=signal.confidence,
            details=json.dumps(signal.details) if signal.details else None,
        ))

    if device is not None:
        device.total_checkins = (device.total_checkins or 0) + 1
        device.last_seen_at = now

    risk_score_histogram.observe(assessment.risk_score)
    if assessment.status == "approved":
        checkin_success_total.inc()
    elif assessment.status == "flagged":
        checkins_flagged_total.inc()

    outcome_action = {"approved": "checkin_approved", "flagged": "checkin_flagged", "rejected": "checkin_rejected"}[
        assessment.status
    ]
    log_event(
        db, outcome_action, user_id=current_user.id, resource_type="checkin", resource_id=checkin.id,
        details={"risk_score": assessment.risk_score, "status": assessment.status},
    )

    db.commit()
    db.refresh(checkin)
    return _to_full_response(checkin)


# =============================================================================
# GET /checkins/ (instructor/admin, paginated)
# =============================================================================

@router.get("/", response_model=Page[CheckinListItem])
def list_checkins(
    session_id: Optional[str] = None,
    course_id: Optional[str] = None,
    student_id: Optional[str] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    min_risk_score: Optional[float] = None,
    max_risk_score: Optional[float] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role("instructor", "ta", "admin")),
    db: Session = Depends(get_db),
):
    query = (
        db.query(CheckIn)
        .join(ClassSession, CheckIn.session_id == ClassSession.id)
        .options(joinedload(CheckIn.session), joinedload(CheckIn.student))
    )
    scope = _scope_sessions_for_staff(db, current_user)
    if scope is not None:
        query = query.filter(scope)

    if session_id:
        query = query.filter(CheckIn.session_id == session_id)
    if course_id:
        query = query.filter(ClassSession.course_id == course_id)
    if student_id:
        query = query.filter(CheckIn.student_id == student_id)
    if status_filter:
        query = query.filter(CheckIn.status == status_filter)
    if min_risk_score is not None:
        query = query.filter(CheckIn.risk_score >= min_risk_score)
    if max_risk_score is not None:
        query = query.filter(CheckIn.risk_score <= max_risk_score)
    if start_date:
        query = query.filter(CheckIn.checked_in_at >= start_date)
    if end_date:
        query = query.filter(CheckIn.checked_in_at <= end_date)

    total = query.count()
    checkins = query.order_by(CheckIn.checked_in_at.desc()).offset(offset).limit(limit).all()
    items = [
        CheckinListItem(
            id=c.id, session_id=c.session_id, session_name=c.session.name, student_id=c.student_id,
            student_name=c.student.full_name, student_email=c.student.email, status=c.status,
            checked_in_at=c.checked_in_at, distance_from_venue_meters=c.distance_from_venue_meters,
            risk_score=c.risk_score, liveness_passed=c.liveness_passed,
        )
        for c in checkins
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


# =============================================================================
# GET /checkins/my-checkins (student)
# =============================================================================

@router.get("/my-checkins", response_model=List[MyCheckinItem])
def my_checkins(
    course_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_role("student")),
    db: Session = Depends(get_db),
):
    query = (
        db.query(CheckIn)
        .join(ClassSession, CheckIn.session_id == ClassSession.id)
        .options(joinedload(CheckIn.session).joinedload(ClassSession.course))
        .filter(CheckIn.student_id == current_user.id)
    )
    if course_id:
        query = query.filter(ClassSession.course_id == course_id)

    checkins = query.order_by(CheckIn.checked_in_at.desc()).limit(limit).all()
    return [
        MyCheckinItem(
            id=c.id, session_id=c.session_id, session_name=c.session.name, course_code=c.session.course.code,
            status=c.status, checked_in_at=c.checked_in_at, risk_score=c.risk_score,
        )
        for c in checkins
    ]


# =============================================================================
# GET /checkins/session/{session_id} (instructor/ta)
# =============================================================================

@router.get("/session/{session_id}", response_model=List[SessionCheckinItem])
def session_checkins(
    session_id: str,
    current_user: User = Depends(require_role("instructor", "ta", "admin")),
    db: Session = Depends(get_db),
):
    session_obj = db.query(ClassSession).filter(ClassSession.id == session_id).first()
    if session_obj is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Session not found", ErrorCode.SESSION_NOT_FOUND)
    require_manage_session(db, current_user, session_obj)

    checkins = (
        db.query(CheckIn)
        .options(joinedload(CheckIn.student), joinedload(CheckIn.device))
        .filter(CheckIn.session_id == session_id)
        .order_by(CheckIn.checked_in_at.desc())
        .all()
    )
    return [
        SessionCheckinItem(
            id=c.id, student_id=c.student_id, student_name=c.student.full_name, student_email=c.student.email,
            status=c.status, checked_in_at=c.checked_in_at, distance_from_venue_meters=c.distance_from_venue_meters,
            risk_score=c.risk_score, risk_factors=_parse_risk_factors(c.risk_factors),
            liveness_passed=c.liveness_passed, device_trusted=c.device.is_trusted if c.device else None,
        )
        for c in checkins
    ]


# =============================================================================
# GET /checkins/flagged (instructor/ta)
# =============================================================================

@router.get("/flagged", response_model=Page[FlaggedCheckinItem])
def flagged_checkins(
    course_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role("instructor", "ta", "admin")),
    db: Session = Depends(get_db),
):
    query = (
        db.query(CheckIn)
        .join(ClassSession, CheckIn.session_id == ClassSession.id)
        .options(joinedload(CheckIn.session), joinedload(CheckIn.student))
        .filter(CheckIn.status.in_(["flagged", "appealed"]))
    )
    scope = _scope_sessions_for_staff(db, current_user)
    if scope is not None:
        query = query.filter(scope)
    if course_id:
        query = query.filter(ClassSession.course_id == course_id)
    if session_id:
        query = query.filter(CheckIn.session_id == session_id)

    total = query.count()
    checkins = query.order_by(CheckIn.checked_in_at.desc()).offset(offset).limit(limit).all()
    items = [
        FlaggedCheckinItem(
            id=c.id, session_id=c.session_id, session_name=c.session.name, student_id=c.student_id,
            student_name=c.student.full_name, status=c.status, checked_in_at=c.checked_in_at,
            risk_score=c.risk_score,
            risk_factors=[
                FlaggedCheckinRiskFactor(type=rf.type, severity="medium", weight=rf.weight)
                for rf in _parse_risk_factors(c.risk_factors)
            ],
            appeal_reason=c.appeal_reason, appealed_at=c.appealed_at,
        )
        for c in checkins
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


# =============================================================================
# GET /checkins/{checkin_id}
# =============================================================================

@router.get("/{checkin_id}", response_model=CheckinResponse)
def get_checkin(checkin_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    checkin = db.get(CheckIn, checkin_id)
    if checkin is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Check-in not found", ErrorCode.CHECKIN_NOT_FOUND)

    if checkin.student_id != current_user.id:
        session_obj = db.get(ClassSession, checkin.session_id)
        if current_user.role == "student" or not can_manage_session(db, current_user, session_obj):
            raise APIError(status.HTTP_403_FORBIDDEN, "Not authorized for this check-in", ErrorCode.INSUFFICIENT_PERMISSIONS)

    return _to_full_response(checkin)


# =============================================================================
# POST /checkins/{id}/appeal (student, owner only)
# =============================================================================

@router.post("/{checkin_id}/appeal", response_model=CheckinAppealResponse)
def appeal_checkin(
    checkin_id: str,
    payload: CheckinAppealRequest,
    current_user: User = Depends(require_role("student")),
    db: Session = Depends(get_db),
):
    checkin = db.get(CheckIn, checkin_id)
    if checkin is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Check-in not found", ErrorCode.CHECKIN_NOT_FOUND)
    if checkin.student_id != current_user.id:
        raise APIError(status.HTTP_403_FORBIDDEN, "Not authorized for this check-in", ErrorCode.INSUFFICIENT_PERMISSIONS)

    if checkin.appealed_at is not None:
        raise APIError(status.HTTP_400_BAD_REQUEST, "Check-in has already been appealed", ErrorCode.ALREADY_APPEALED)
    if checkin.status not in ("flagged", "rejected"):
        raise APIError(
            status.HTTP_400_BAD_REQUEST, "Only flagged or rejected check-ins can be appealed", ErrorCode.APPEAL_NOT_ALLOWED
        )
    if _now() - checkin.checked_in_at > timedelta(days=APPEAL_WINDOW_DAYS):
        raise APIError(status.HTTP_400_BAD_REQUEST, "Appeal window has expired", ErrorCode.APPEAL_WINDOW_EXPIRED)

    checkin.status = "appealed"
    checkin.appeal_reason = payload.appeal_reason
    checkin.appealed_at = _now()

    log_event(
        db, "checkin_appealed", user_id=current_user.id, resource_type="checkin", resource_id=checkin.id,
        details={"appeal_reason": payload.appeal_reason},
    )
    db.commit()
    db.refresh(checkin)
    return CheckinAppealResponse(
        id=checkin.id, status=checkin.status, appeal_reason=checkin.appeal_reason, appealed_at=checkin.appealed_at
    )


# =============================================================================
# POST /checkins/{id}/review (instructor/ta for the session's course)
# =============================================================================

@router.post("/{checkin_id}/review", response_model=CheckinReviewResponse)
def review_checkin(
    checkin_id: str,
    payload: CheckinReviewRequest,
    current_user: User = Depends(require_role("instructor", "ta", "admin")),
    db: Session = Depends(get_db),
):
    checkin = db.get(CheckIn, checkin_id)
    if checkin is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Check-in not found", ErrorCode.CHECKIN_NOT_FOUND)

    session_obj = db.get(ClassSession, checkin.session_id)
    require_manage_session(db, current_user, session_obj)

    if checkin.status not in ("flagged", "appealed"):
        raise APIError(
            status.HTTP_400_BAD_REQUEST, "Only flagged or appealed check-ins can be reviewed", ErrorCode.REVIEW_NOT_ALLOWED
        )

    checkin.status = payload.status
    checkin.reviewed_by_id = current_user.id
    checkin.reviewed_at = _now()
    checkin.review_notes = payload.review_notes

    log_event(
        db, "checkin_reviewed", user_id=current_user.id, resource_type="checkin", resource_id=checkin.id,
        details={"status": payload.status, "review_notes": payload.review_notes},
    )
    db.commit()
    db.refresh(checkin)
    return CheckinReviewResponse(
        id=checkin.id, status=checkin.status, reviewed_by_id=checkin.reviewed_by_id,
        reviewed_at=checkin.reviewed_at, review_notes=checkin.review_notes,
    )
