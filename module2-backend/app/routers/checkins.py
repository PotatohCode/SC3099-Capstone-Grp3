"""
Check-in submission, review, and query endpoints (Task 2.7). The core
pipeline (geofencing, risk scoring, Face Service calls) lives in
services/geofencing.py, services/risk_scoring.py, services/face_client.py -
this router stays thin per IMPLEMENTATION-PLAN.md's own rule.

See KNOWN-ISSUES.md before touching the decision logic: the hard override
(liveness explicitly failed, or GPS > 2x geofence radius -> rejected
regardless of score) is not a pure `risk_score < threshold` comparison,
and every Module 3 call has a degrade-gracefully path (timeout, error or
4xx -> None), so a check-in never fails because the face service is down.
"""
import base64
import binascii
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import get_settings
from app.core.deps import get_current_user, get_db, require_role
from app.core.errors import APIError, ErrorCode
from app.core.metrics import (
    checkin_attempts_total,
    checkin_rejected_geo_total,
    checkin_success_total,
    checkins_flagged_total,
    risk_score_histogram,
)
from app.db.models.checkin import CheckIn
from app.db.models.device import Device
from app.db.models.enrollment import Enrollment
from app.db.models.liveness_frame_hash import LivenessFrameHash
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
    LivenessChallengeRequest,
    LivenessChallengeResponse,
    LivenessVerifyRequest,
    LivenessVerifyResponse,
    ManualCheckinRequest,
    ManualUndoResponse,
    MyCheckinItem,
    RiskFactorItem,
    SessionCheckinItem,
)
from app.schemas.common import Page, page_limit
from app.services import face_client, geofencing, liveness_challenge, risk_scoring, singapore_check
from app.services.audit import log_event, log_security_violation
from app.services.client_ip import get_client_ip
from app.services.liveness_challenge import Outcome
from app.services.authz import can_manage_session, require_manage_session
from app.services.rate_limit import enforce_rate_limit
from app.services.sanitize import sanitize_text
from app.services.uploads import require_frames_size, require_image_size

router = APIRouter(prefix="/checkins", tags=["checkins"])
settings = get_settings()

APPEAL_WINDOW_DAYS = 7
CHALLENGES_PER_MINUTE = 30  # per student; a retry needs a fresh challenge


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _image_hash(image_b64: str) -> str:
    """SHA-256 of the decoded image bytes (data-URL prefix and whitespace
    ignored), so the same photo re-encoded with different padding or line
    breaks still matches. Falls back to hashing the raw string if it isn't
    valid base64."""
    data = image_b64.split(",", 1)[1] if image_b64.startswith("data:") else image_b64
    try:
        raw = base64.b64decode("".join(data.split()), validate=True)
    except (binascii.Error, ValueError):
        raw = image_b64.encode()
    return hashlib.sha256(raw).hexdigest()


def _submission_hash(image_hashes: List[str]) -> str:
    """What goes in checkins.liveness_image_hash: the photo's own hash for a
    single image (unchanged from before frame bursts), otherwise one hash
    over the burst's frame hashes in order. Replay detection itself uses the
    per-image rows in liveness_frame_hashes."""
    if len(image_hashes) == 1:
        return image_hashes[0]
    return hashlib.sha256(":".join(image_hashes).encode()).hexdigest()


def _stored_challenge_type(
    sequence: Optional[List[str]], challenge_attempted: bool, client_type: Optional[str], has_image: bool
) -> Optional[str]:
    """checkins.liveness_challenge_type: the server-issued sequence
    ("blink,turn_left"); "sequence" if a challenge was named but couldn't be
    read (Redis down); else the client's declared type or "passive" when
    there was an image; None without one."""
    if sequence:
        return ",".join(sequence)
    if challenge_attempted:
        return "sequence"
    if has_image:
        return client_type or "passive"
    return None


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
        entry_method=checkin.entry_method,
    )


def _flagged_risk_factors(checkin: CheckIn) -> List[FlaggedCheckinRiskFactor]:
    """risk_factors with each signal's real severity (critical/high/medium/
    low), taken from the risk_signals rows written alongside them. "medium"
    only if a factor somehow has no matching row."""
    severity_by_type = {s.signal_type: s.severity for s in checkin.risk_signals}
    return [
        FlaggedCheckinRiskFactor(type=rf.type, severity=severity_by_type.get(rf.type, "medium"), weight=rf.weight)
        for rf in _parse_risk_factors(checkin.risk_factors)
    ]


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
    require_image_size(payload.liveness_challenge_response)
    require_frames_size(payload.liveness_challenge_frames)
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

    # --- Consent (config CONSENT_ENFORCEMENT; off by default) ----------------
    consent_ok = bool(current_user.camera_consent and current_user.geolocation_consent)
    if settings.CONSENT_ENFORCEMENT == "reject" and not consent_ok:
        raise APIError(
            status.HTTP_403_FORBIDDEN, "Camera and location consent are required before checking in",
            ErrorCode.CONSENT_REQUIRED,
        )

    # --- Singapore-only rule (graded; see services/singapore_check.py) -------
    # After the session/enrollment/window/duplicate guards so their status
    # codes are unchanged, and before any Module 3 round-trips. 403 rather
    # than a stored "rejected" row: a stored row would trip the
    # ALREADY_CHECKED_IN guard above and stop the student retrying once
    # they're genuinely back in Singapore (e.g. VPN switched off).
    client_ip = get_client_ip(request)
    gps_ok = singapore_check.coords_in_singapore(payload.latitude, payload.longitude)
    ip_ok = singapore_check.ip_allowed(client_ip)
    if not (gps_ok and ip_ok):
        reason = "gps_and_ip" if not (gps_ok or ip_ok) else ("gps" if not gps_ok else "ip")
        checkin_rejected_geo_total.labels(reason=reason).inc()
        log_event(
            db, "checkin_rejected_geo", user_id=current_user.id, resource_type="session",
            resource_id=session_obj.id, ip_address=client_ip, user_agent=request.headers.get("user-agent"),
            success=False,
            # No raw coordinates here - audit logs aren't covered by the
            # check-in PII retention sweep, so only record the verdicts.
            details={
                "reason": reason,
                "gps_in_singapore": gps_ok,
                "ip_country": None if ip_ok else singapore_check.ip_country(client_ip),
            },
        )
        log_security_violation(
            db, "outside_singapore", user_id=current_user.id, resource_type="session", resource_id=session_obj.id,
            ip_address=client_ip, user_agent=request.headers.get("user-agent"), details={"reason": reason},
        )
        db.commit()
        raise APIError(
            status.HTTP_403_FORBIDDEN, "Check-in only allowed from within Singapore", ErrorCode.OUTSIDE_SINGAPORE
        )

    # --- Liveness challenge (services/liveness_challenge.py) -----------------
    # Consumed before any Module 3 call, so a challenge is single use even if
    # this check-in fails later. A bad challenge stores nothing (400), so the
    # app can fetch a new one and retry.
    challenge_sequence: Optional[List[str]] = None
    challenge_attempted = False
    # Set when the challenge went through POST /challenge/{id}/verify first.
    verified: Optional[liveness_challenge.ConsumeResult] = None
    if payload.challenge_id:
        challenge_attempted = True
        consumed = liveness_challenge.consume(payload.challenge_id, current_user.id, session_obj.id)
        if consumed.status == liveness_challenge.ConsumeStatus.OK:
            challenge_sequence = consumed.sequence
            if consumed.outcome is not None:
                verified = consumed
        elif consumed.status != liveness_challenge.ConsumeStatus.UNAVAILABLE:
            # UNAVAILABLE (Redis down) falls through as "challenged but
            # unverifiable", which caps the outcome at flagged below.
            if consumed.status in (
                liveness_challenge.ConsumeStatus.REUSED, liveness_challenge.ConsumeStatus.OTHER_STUDENT
            ):
                log_security_violation(
                    db, "challenge_reuse", user_id=current_user.id, resource_type="session",
                    resource_id=session_obj.id, ip_address=client_ip, user_agent=request.headers.get("user-agent"),
                    details={"reason": consumed.status.value},
                )
                db.commit()
            raise APIError(
                status.HTTP_400_BAD_REQUEST, "Liveness challenge is invalid or expired; request a new one",
                ErrorCode.CHALLENGE_INVALID,
            )

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

    # --- Images: one photo and/or a frame burst --------------------------------
    frames = payload.liveness_challenge_frames or []
    images = ([payload.liveness_challenge_response] if payload.liveness_challenge_response else []) + frames
    # One image for face verify and for older Module 3 builds: the photo if
    # sent, else the middle frame of the burst.
    primary_image = payload.liveness_challenge_response or (frames[len(frames) // 2] if frames else None)

    # --- Replay check: same student re-submitting any previously used image --
    # Per image, so reusing even one frame of an earlier burst is caught.
    image_hashes = [_image_hash(img) for img in images]
    unique_image_hashes = list(dict.fromkeys(image_hashes))
    liveness_image_hash: Optional[str] = _submission_hash(image_hashes) if image_hashes else None
    replay_suspected = bool(unique_image_hashes) and (
        db.query(LivenessFrameHash.id)
        .filter(
            LivenessFrameHash.student_id == current_user.id, LivenessFrameHash.frame_hash.in_(unique_image_hashes)
        )
        .first()
        is not None
    )

    # --- Proxy sign-in: same device used by other students just now --------
    device_fingerprint_hash = hashlib.sha256(payload.device_fingerprint.encode()).hexdigest()
    other_students_on_device = (
        db.query(func.count(func.distinct(CheckIn.student_id)))
        .filter(
            CheckIn.device_fingerprint_hash == device_fingerprint_hash,
            CheckIn.student_id != current_user.id,
            CheckIn.checked_in_at >= now - timedelta(minutes=10),
        )
        .scalar()
    )
    minutes_after_start = (now - session_obj.scheduled_start).total_seconds() / 60

    # Hand the DB connection back to the pool while Module 3 is called (up to
    # 5 s per call, 15 s for a frame burst). Holding it across those calls
    # let ~30 slow check-ins take the whole pool (10 + 20 overflow), so every
    # other request queued behind them (measured: face service hung + 100
    # check-ins -> a plain GET took 9.5 s). Nothing is pending at this point,
    # so this only ends the read transaction; objects reload on next access.
    db.commit()

    # --- Liveness + face match (defensive: 5s timeout, degrade on failure) --
    liveness_passed: Optional[bool] = None
    liveness_score = 0.0
    face_match_passed: Optional[bool] = None
    face_match_score: Optional[float] = None
    current_face_hash: Optional[str] = None

    challenge_passed: Optional[bool] = None
    challenge_failed = False

    # A verified pass only counts for the burst it was verified on (compared
    # by hash; no images are kept). Otherwise someone could pass the
    # movements with their own face, then send a photo of the enrolled
    # student for the face match.
    use_verified = False
    if verified is not None and verified.outcome == Outcome.PASSED:
        frames_hash = _submission_hash([_image_hash(f) for f in frames]) if frames else None
        if frames_hash is not None and frames_hash == verified.frames_hash:
            use_verified = True
        else:
            log_security_violation(
                db, "challenge_frames_mismatch", user_id=current_user.id, resource_type="session",
                resource_id=session_obj.id, ip_address=client_ip, user_agent=request.headers.get("user-agent"),
            )

    if use_verified:
        liveness_passed = True
        liveness_score = verified.liveness_score or 0.0
        challenge_passed = True
        primary_image = frames[len(frames) // 2]  # the face match runs on the verified burst
    elif verified is not None and verified.outcome == Outcome.FAILED:
        challenge_failed = True
    elif verified is not None and verified.outcome == Outcome.SPOOF:
        liveness_passed = False
    elif verified is not None and verified.outcome == Outcome.PASSED:
        pass  # different burst: the pass doesn't count, liveness unverified
    elif primary_image:
        # Never verified (or Module 3 couldn't answer at verify): checked here.
        sent_challenge_type = "sequence" if challenge_attempted else (payload.challenge_type or "passive")
        liveness_result = face_client.check_liveness(
            primary_image, sent_challenge_type, frames=frames or None, challenge_sequence=challenge_sequence
        )
        if liveness_result is not None:
            liveness_passed = liveness_result.get("liveness_passed")
            liveness_score = liveness_result.get("liveness_score", 0.0) or 0.0
            challenge_passed = liveness_result.get("challenge_passed")

        # A challenged check-in needs Module 3 to confirm the steps. Not
        # performed -> review (liveness_challenge_failed), never an
        # auto-reject: at ~5 fps a genuine student can miss them. No answer
        # (older build, Redis down, call failed) -> unverified, so it's never
        # auto-approved; a spoof verdict (False) still stands.
        if challenge_attempted:
            if challenge_passed is False:
                challenge_failed = True
                if liveness_passed is not False:
                    liveness_passed = None
            elif challenge_passed is not True and liveness_passed is not False:
                liveness_passed = None

    # Earlier verify attempts for this session count whatever this check-in
    # sends, so skipping the challenge after failing it doesn't help: a
    # spoof verdict rejects, and after a failed attempt only a verified pass
    # can approve.
    attempts = liveness_challenge.attempt_state(current_user.id, session_obj.id)
    if attempts is not None:
        if attempts.spoof:
            liveness_passed = False
        elif attempts.failed > 0 and not use_verified:
            challenge_failed = True
            if liveness_passed is True:
                liveness_passed = None

    if primary_image and current_user.face_embedding_hash:
        verify_result = face_client.verify_face(primary_image, current_user.face_embedding_hash)
        if verify_result is not None:
            face_match_passed = verify_result.get("match_passed")
            face_match_score = verify_result.get("match_score")
            current_face_hash = verify_result.get("current_template_hash")

    # LIVENESS_CHALLENGE_ENFORCEMENT=flag: on a liveness-required session,
    # only a passed server-issued challenge counts as verified liveness.
    if (
        settings.LIVENESS_CHALLENGE_ENFORCEMENT == "flag"
        and session_obj.require_liveness_check
        and not (challenge_sequence and challenge_passed is True)
        and liveness_passed is True
    ):
        liveness_passed = None

    # --- Risk scoring: prefer Module 3's /risk/assess, else local fallback --
    # Only worth the round-trip if we actually have image-derived signals
    # to send - with neither, 3 of Module 3's 5 weighted signals (liveness,
    # face_match, and effectively device) would be blank anyway, and the
    # geo signal is already computed independently via geofencing above.
    remote_risk = None
    if primary_image:
        risk_request = {
            "liveness_score": liveness_score,
            "face_match_score": face_match_score,
            "user_agent": request.headers.get("user-agent"),
            "ip_address": get_client_ip(request),
        }
        # Module 3 requires geolocation.accuracy to be a number (422 otherwise),
        # and location_accuracy_meters is optional for us - without it, leave
        # geolocation out; our own geofence check above still applies.
        if payload.location_accuracy_meters is not None:
            risk_request["geolocation"] = {
                "latitude": payload.latitude, "longitude": payload.longitude, "accuracy": payload.location_accuracy_meters,
            }
        remote_risk = face_client.assess_risk(risk_request)
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
        face_match_passed=face_match_passed,
        require_liveness=bool(session_obj.require_liveness_check),
        require_face_match=bool(session_obj.require_face_match or course.require_face_recognition),
        replay_suspected=replay_suspected,
        other_students_on_device=other_students_on_device,
        minutes_after_start=minutes_after_start,
        consent_missing=settings.CONSENT_ENFORCEMENT == "flag" and not consent_ok,
        device_unbound=(
            settings.DEVICE_BINDING_ENFORCEMENT == "flag" and bool(course.require_device_binding) and not device_known
        ),
        challenge_failed=challenge_failed,
        flag_face_mismatch=settings.FACE_MISMATCH_ENFORCEMENT == "flag",
    )

    log_event(
        db, "checkin_attempted", user_id=current_user.id, resource_type="session", resource_id=session_obj.id,
        ip_address=get_client_ip(request), user_agent=request.headers.get("user-agent"),
        details={"session_id": session_obj.id, "device_fingerprint": payload.device_fingerprint},
    )

    checkin = CheckIn(
        session_id=session_obj.id,
        student_id=current_user.id,
        device_id=device.id if device else None,
        status=assessment.status,
        checked_in_at=now,
        verified_at=now,
        latitude=round(payload.latitude, settings.LOCATION_STORAGE_DECIMALS),
        longitude=round(payload.longitude, settings.LOCATION_STORAGE_DECIMALS),
        location_accuracy_meters=payload.location_accuracy_meters,
        distance_from_venue_meters=distance,
        liveness_passed=liveness_passed,
        liveness_score=liveness_score,
        liveness_challenge_type=_stored_challenge_type(
            challenge_sequence, challenge_attempted, payload.challenge_type, bool(primary_image)
        ),
        face_match_passed=face_match_passed,
        face_match_score=face_match_score,
        face_embedding_hash=current_face_hash,
        liveness_image_hash=liveness_image_hash,
        device_fingerprint_hash=device_fingerprint_hash,
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

    for frame_hash in unique_image_hashes:
        db.add(LivenessFrameHash(checkin_id=checkin.id, student_id=current_user.id, frame_hash=frame_hash))

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
        # risk_level makes "MEDIUM: auto-approve with logging" visible in the
        # audit trail without re-deriving bands from the score.
        details={"risk_score": assessment.risk_score, "risk_level": assessment.risk_level, "status": assessment.status},
    )
    for violation in assessment.violation_types:
        log_security_violation(
            db, violation, user_id=current_user.id, resource_type="checkin", resource_id=checkin.id,
            ip_address=get_client_ip(request), user_agent=request.headers.get("user-agent"),
            details={"session_id": session_obj.id, "status": assessment.status},
        )

    db.commit()
    db.refresh(checkin)
    return _to_full_response(checkin)


# =============================================================================
# POST /checkins/challenge
# =============================================================================

@router.post("/challenge", response_model=LivenessChallengeResponse, status_code=status.HTTP_201_CREATED)
def issue_liveness_challenge(
    payload: LivenessChallengeRequest,
    current_user: User = Depends(require_role("student")),
    db: Session = Depends(get_db),
):
    """Random liveness challenge for the next check-in (see
    services/liveness_challenge.py). Same session guards as a check-in, so
    the app learns early that it can't check in at all."""
    enforce_rate_limit(f"rate_limit:{current_user.id}:challenge", CHALLENGES_PER_MINUTE, 60)

    session_obj = db.query(ClassSession).filter(ClassSession.id == payload.session_id).first()
    if session_obj is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Session not found", ErrorCode.SESSION_NOT_FOUND)
    is_enrolled = (
        db.query(Enrollment.id)
        .filter(
            Enrollment.student_id == current_user.id,
            Enrollment.course_id == session_obj.course_id,
            Enrollment.is_active.is_(True),
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

    try:
        issued = liveness_challenge.issue(current_user.id, session_obj.id, session_obj.checkin_closes_at)
    except liveness_challenge.AttemptsExhausted:
        raise APIError(
            status.HTTP_409_CONFLICT, "No liveness attempts left for this session; submit the check-in for review",
            ErrorCode.LIVENESS_ATTEMPTS_EXHAUSTED,
        )
    except liveness_challenge.ChallengeUnavailable:
        raise APIError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Liveness challenges are temporarily unavailable",
            ErrorCode.CHALLENGE_UNAVAILABLE,
        )
    return LivenessChallengeResponse(
        challenge_id=issued.challenge_id, session_id=session_obj.id, sequence=issued.sequence,
        expires_at=issued.expires_at, max_frames=settings.MAX_LIVENESS_FRAMES, attempts_left=issued.attempts_left,
    )


# =============================================================================
# POST /checkins/challenge/{challenge_id}/verify
# =============================================================================

def _classify_liveness(result: Optional[dict]) -> Outcome:
    """Module 3's answer for a challenged burst -> one verify outcome.
    Only `liveness_passed: false` is a spoof verdict (API-FOR-FACE-
    RECOGNITION section 3: never sent for uncertain cases)."""
    if result is None:
        return Outcome.UNVERIFIED
    liveness_passed, challenge_passed = result.get("liveness_passed"), result.get("challenge_passed")
    if liveness_passed is False:
        return Outcome.SPOOF
    if challenge_passed is True and liveness_passed is True:
        return Outcome.PASSED
    if challenge_passed is False:
        return Outcome.FAILED
    return Outcome.UNVERIFIED


def _failed_step(result: Optional[dict], sequence: List[str]) -> Optional[str]:
    """The first step Module 3 reports as not performed, if it reports them."""
    steps = (result or {}).get("steps_passed")
    if not isinstance(steps, list):
        return None
    for action, passed in zip(sequence, steps):
        if passed is False:
            return action
    return None


@router.post("/challenge/{challenge_id}/verify", response_model=LivenessVerifyResponse)
def verify_liveness_challenge(
    challenge_id: str,
    payload: LivenessVerifyRequest,
    request: Request,
    current_user: User = Depends(require_role("student")),
    db: Session = Depends(get_db),
):
    """Checks a challenge's frame burst before the check-in, so the student
    can retry (services/liveness_challenge.py). Uses up the challenge either
    way; a retry needs a new one."""
    enforce_rate_limit(f"rate_limit:{current_user.id}:challenge_verify", CHALLENGES_PER_MINUTE, 60)
    require_frames_size(payload.frames)
    client_ip, ua = get_client_ip(request), request.headers.get("user-agent")
    student_id = current_user.id

    ConsumeStatus = liveness_challenge.ConsumeStatus
    start = liveness_challenge.begin_verify(challenge_id, student_id)
    if start.status == ConsumeStatus.UNAVAILABLE:
        # Redis down: nothing counted; the check-in then goes to review.
        return LivenessVerifyResponse(result="unverified")
    if start.status == ConsumeStatus.EXHAUSTED:
        raise APIError(
            status.HTTP_409_CONFLICT, "No liveness attempts left for this session; submit the check-in for review",
            ErrorCode.LIVENESS_ATTEMPTS_EXHAUSTED,
        )
    if start.status != ConsumeStatus.OK:
        if start.status in (ConsumeStatus.REUSED, ConsumeStatus.OTHER_STUDENT):
            log_security_violation(
                db, "challenge_reuse", user_id=student_id, resource_type="liveness_challenge",
                ip_address=client_ip, user_agent=ua, details={"reason": start.status.value},
            )
            db.commit()
        raise APIError(
            status.HTTP_400_BAD_REQUEST, "Liveness challenge is invalid or expired; request a new one",
            ErrorCode.CHALLENGE_INVALID,
        )

    frames = payload.frames
    # Don't hold a DB connection while Module 3 works (up to 15 s for a burst).
    db.commit()
    result = face_client.check_liveness(
        frames[len(frames) // 2], "sequence", frames=frames, challenge_sequence=start.sequence
    )
    outcome = _classify_liveness(result)
    liveness_score = float((result or {}).get("liveness_score") or 0.0)
    frames_hash = _submission_hash([_image_hash(f) for f in frames])
    attempts_left = liveness_challenge.finish_verify(
        challenge_id, student_id, start, outcome, frames_hash, liveness_score
    )

    failed_step = _failed_step(result, start.sequence or []) if outcome == Outcome.FAILED else None
    log_event(
        db, "liveness_challenge_verified", user_id=student_id, resource_type="session", resource_id=start.session_id,
        ip_address=client_ip, user_agent=ua, success=outcome == Outcome.PASSED,
        details={
            "outcome": outcome.value, "attempt": start.attempt, "sequence": start.sequence,
            "steps_passed": (result or {}).get("steps_passed"), "liveness_score": liveness_score,
        },
    )
    if outcome == Outcome.SPOOF:
        log_security_violation(
            db, "liveness_spoof", user_id=student_id, resource_type="session", resource_id=start.session_id,
            ip_address=client_ip, user_agent=ua, details={"attempt": start.attempt},
        )
    db.commit()

    if outcome == Outcome.SPOOF:
        # Reported like running out of tries, so the client can't tell.
        return LivenessVerifyResponse(result="failed", attempts_left=0)
    return LivenessVerifyResponse(
        result=outcome.value,
        attempts_left=attempts_left,
        failed_step=failed_step if settings.LIVENESS_FEEDBACK == "per_step" else None,
    )


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
    limit: int = Query(default=50, ge=1),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role("instructor", "ta", "admin")),
    db: Session = Depends(get_db),
):
    limit = page_limit(limit)
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
            risk_score=c.risk_score, liveness_passed=c.liveness_passed, entry_method=c.entry_method,
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
    limit: int = Query(default=50, ge=1),
    current_user: User = Depends(require_role("student")),
    db: Session = Depends(get_db),
):
    limit = page_limit(limit)
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
            entry_method=c.entry_method,
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
    limit: int = Query(default=50, ge=1),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role("instructor", "ta", "admin")),
    db: Session = Depends(get_db),
):
    limit = page_limit(limit)
    query = (
        db.query(CheckIn)
        .join(ClassSession, CheckIn.session_id == ClassSession.id)
        .options(joinedload(CheckIn.session), joinedload(CheckIn.student), selectinload(CheckIn.risk_signals))
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
            risk_factors=_flagged_risk_factors(c),
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
    checkin.appeal_reason = sanitize_text(payload.appeal_reason)
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
    checkin.review_notes = sanitize_text(payload.review_notes) if payload.review_notes else payload.review_notes

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


# =============================================================================
# POST /checkins/manual + /checkins/{id}/manual/undo (instructor/ta)
# =============================================================================
# Team decision 2026-10-27: staff who saw the student in class can mark
# them present when the app couldn't (phone dead, camera broken, GPS
# refused). Creates the check-in, or approves a flagged/appealed/rejected
# one in place (the evidence is kept). Undo restores exactly what was
# there. Both until MANUAL_CHECKIN_DAYS after the session's scheduled end.
# Not counted in the Prometheus check-in metrics (they'd skew the success
# rate of real check-ins).

MANUAL_FACTOR = "manual_checkin"
OVERRIDE_FACTOR = "manual_override"


def _require_manual_window(session_obj: ClassSession) -> None:
    """By the session's times, not its status: staff set the status by hand,
    so a class that happened may still say "scheduled" or "active"."""
    if session_obj.status == "cancelled":
        raise APIError(status.HTTP_400_BAD_REQUEST, "Session was cancelled", ErrorCode.SESSION_NOT_ACTIVE)
    now = _now()
    if now < session_obj.checkin_opens_at:
        raise APIError(status.HTTP_400_BAD_REQUEST, "Session hasn't started yet", ErrorCode.SESSION_NOT_ACTIVE)
    _require_within_manual_days(session_obj)


def _require_within_manual_days(session_obj: ClassSession) -> None:
    if _now() > session_obj.scheduled_end + timedelta(days=settings.MANUAL_CHECKIN_DAYS):
        raise APIError(
            status.HTTP_400_BAD_REQUEST,
            f"Manual check-ins close {settings.MANUAL_CHECKIN_DAYS} days after the session",
            ErrorCode.MANUAL_CHECKIN_WINDOW_CLOSED,
        )


@router.post("/manual", response_model=CheckinResponse, status_code=status.HTTP_201_CREATED)
def manual_checkin(
    payload: ManualCheckinRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(require_role("instructor", "ta", "admin")),
    db: Session = Depends(get_db),
):
    """201 with a new check-in, or 200 when it approved an existing one."""
    session_obj = db.get(ClassSession, payload.session_id)
    if session_obj is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Session not found", ErrorCode.SESSION_NOT_FOUND)
    require_manage_session(db, current_user, session_obj)
    _require_manual_window(session_obj)

    student = db.get(User, payload.student_id)
    if student is None or student.role != "student" or not student.is_active:
        raise APIError(status.HTTP_404_NOT_FOUND, "Student not found", ErrorCode.STUDENT_NOT_FOUND)
    is_enrolled = (
        db.query(Enrollment)
        .filter(
            Enrollment.student_id == student.id, Enrollment.course_id == session_obj.course_id,
            Enrollment.is_active.is_(True),
        )
        .first()
        is not None
    )
    if not is_enrolled:
        raise APIError(status.HTTP_400_BAD_REQUEST, "Student is not enrolled in this course", ErrorCode.NOT_ENROLLED)

    now = _now()
    reason = sanitize_text(payload.reason)
    client = {"ip_address": get_client_ip(request), "user_agent": request.headers.get("user-agent")}
    # Locked, so a parallel override or undo of the same record waits.
    existing = (
        db.query(CheckIn)
        .filter(CheckIn.session_id == session_obj.id, CheckIn.student_id == student.id)
        .with_for_update()
        .first()
    )

    if existing is None:
        checkin = CheckIn(
            session_id=session_obj.id,
            student_id=student.id,
            status="approved",
            checked_in_at=now,
            verified_at=now,
            risk_score=0.0,
            risk_factors=json.dumps([{"type": MANUAL_FACTOR, "weight": 0.0}]),
            reviewed_by_id=current_user.id,
            reviewed_at=now,
            review_notes=reason,
            entry_method="manual",
            scheduled_deletion_at=now + timedelta(days=settings.PII_RETENTION_DAYS),
        )
        db.add(checkin)
        # A parallel create (staff or the student) hits
        # uq_checkin_session_student -> 400 ALREADY_CHECKED_IN (main.py).
        db.flush()
        log_event(
            db, "checkin_manual", user_id=current_user.id, resource_type="checkin", resource_id=checkin.id,
            details={"student_id": student.id, "session_id": session_obj.id, "reason": payload.reason}, **client,
        )
    else:
        if existing.status == "approved":
            raise APIError(
                status.HTTP_400_BAD_REQUEST, "Already checked in (approved) for this session",
                ErrorCode.ALREADY_CHECKED_IN,
            )
        checkin = existing
        previous_status = checkin.status
        checkin.override_previous = json.dumps({
            "status": checkin.status,
            "entry_method": checkin.entry_method,
            "reviewed_by_id": checkin.reviewed_by_id,
            "reviewed_at": checkin.reviewed_at.isoformat() if checkin.reviewed_at else None,
            "review_notes": checkin.review_notes,
        })
        factors = json.loads(checkin.risk_factors) if checkin.risk_factors else []
        factors.append({"type": OVERRIDE_FACTOR, "weight": 0.0})
        checkin.risk_factors = json.dumps(factors)
        checkin.status = "approved"
        checkin.entry_method = "override"
        checkin.reviewed_by_id = current_user.id
        checkin.reviewed_at = now
        checkin.review_notes = reason
        log_event(
            db, "checkin_manual_override", user_id=current_user.id, resource_type="checkin", resource_id=checkin.id,
            details={
                "student_id": student.id, "session_id": session_obj.id, "previous_status": previous_status,
                "reason": payload.reason,
            },
            **client,
        )
        response.status_code = status.HTTP_200_OK

    db.commit()
    db.refresh(checkin)
    return _to_full_response(checkin)


@router.post("/{checkin_id}/manual/undo", response_model=ManualUndoResponse)
def undo_manual_checkin(
    checkin_id: str,
    request: Request,
    current_user: User = Depends(require_role("instructor", "ta", "admin")),
    db: Session = Depends(get_db),
):
    checkin = db.query(CheckIn).filter(CheckIn.id == checkin_id).with_for_update().first()
    if checkin is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Check-in not found", ErrorCode.CHECKIN_NOT_FOUND)
    session_obj = db.get(ClassSession, checkin.session_id)
    require_manage_session(db, current_user, session_obj)
    if checkin.entry_method not in ("manual", "override"):
        raise APIError(
            status.HTTP_400_BAD_REQUEST, "Only manual check-ins and overrides can be undone",
            ErrorCode.MANUAL_UNDO_NOT_ALLOWED,
        )
    _require_within_manual_days(session_obj)

    undone = checkin.entry_method
    details = {"student_id": checkin.student_id, "session_id": checkin.session_id, "entry_method": undone}
    if undone == "manual":
        # Nothing references a staff-created check-in (no risk signals or
        # frame hashes), and the audit log keeps the history.
        db.delete(checkin)
        result_status = "deleted"
    else:
        previous = json.loads(checkin.override_previous or "{}")
        result_status = previous.get("status") or "flagged"
        checkin.status = result_status
        checkin.entry_method = previous.get("entry_method") or "app"
        checkin.reviewed_by_id = previous.get("reviewed_by_id")
        reviewed_at = previous.get("reviewed_at")
        checkin.reviewed_at = datetime.fromisoformat(reviewed_at) if reviewed_at else None
        checkin.review_notes = previous.get("review_notes")
        factors = json.loads(checkin.risk_factors) if checkin.risk_factors else []
        checkin.risk_factors = json.dumps([f for f in factors if f.get("type") != OVERRIDE_FACTOR])
        checkin.override_previous = None
    details["restored_status"] = result_status
    log_event(
        db, "checkin_manual_undone", user_id=current_user.id, resource_type="checkin", resource_id=checkin_id,
        ip_address=get_client_ip(request), user_agent=request.headers.get("user-agent"), details=details,
    )
    db.commit()
    return ManualUndoResponse(id=checkin_id, status=result_status)
