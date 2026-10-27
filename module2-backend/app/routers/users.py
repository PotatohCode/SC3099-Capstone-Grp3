from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user, get_db, require_role
from app.core.errors import APIError, ErrorCode
from app.core.security import get_password_hash, verify_password
from app.db.models.user import User
from app.schemas.common import Page, page_limit
from app.schemas.user import (
    AccountDeletionRequest,
    AccountDeletionResponse,
    FaceEnrollRequest,
    FaceEnrollResponse,
    FaceResetCodeResponse,
    PasswordChangeRequest,
    UserAdminUpdate,
    UserResponse,
    UserUpdateRequest,
)
from app.services import account_lockout, face_client, face_reset_code
from app.services.audit import log_event, log_security_violation
from app.services.authz import teaches_student
from app.services.client_ip import get_client_ip
from app.services.partial_update import drop_nulls_for_required
from app.services.sanitize import sanitize_text
from app.services.uploads import require_image_size

router = APIRouter(prefix="/users", tags=["users"])
settings = get_settings()


def _schedule_deletion(db: Session, user: User, actor_id: str) -> AccountDeletionResponse:
    """Right to deletion (Briefing p.27). SECURITY-REQUIREMENTS "User PII:
    30 days after deletion, scheduled cleanup job": deactivate now (every
    existing token stops working - get_current_user and /auth/refresh both
    require is_active), and let the automatic retention sweep anonymise the
    row once scheduled_deletion_at passes. Idempotent: a repeat keeps the
    original date. Admin PATCH .../activate cancels a pending deletion."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if user.scheduled_deletion_at is None:
        user.scheduled_deletion_at = now + timedelta(days=settings.PII_RETENTION_DAYS)
    user.is_active = False
    log_event(
        db, "user_deletion_requested", user_id=actor_id, resource_type="user", resource_id=user.id,
        details={"scheduled_deletion_at": user.scheduled_deletion_at.isoformat()},
    )
    db.commit()
    return AccountDeletionResponse(
        message="Account deactivated; personal data will be removed on the scheduled date",
        scheduled_deletion_at=user.scheduled_deletion_at,
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=UserResponse)
def update_me(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.full_name is not None:
        current_user.full_name = sanitize_text(payload.full_name)
    if payload.camera_consent is not None:
        current_user.camera_consent = payload.camera_consent
    if payload.geolocation_consent is not None:
        current_user.geolocation_consent = payload.geolocation_consent

    db.commit()
    db.refresh(current_user)
    return current_user


@router.delete("/me", response_model=AccountDeletionResponse, status_code=status.HTTP_202_ACCEPTED)
def delete_me(
    payload: AccountDeletionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.password, current_user.hashed_password):
        raise APIError(status.HTTP_403_FORBIDDEN, "Password is incorrect", ErrorCode.PASSWORD_INCORRECT)
    return _schedule_deletion(db, current_user, actor_id=current_user.id)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A wrong current password counts toward the same lockout as login
    (services/account_lockout.py), so a stolen access token can't be used
    to guess the password here without limit."""
    ip, ua = get_client_ip(request), request.headers.get("user-agent")

    retry_after = account_lockout.locked_retry_after(db, current_user)
    if retry_after is not None:
        log_event(
            db, "password_change_failed", user_id=current_user.id, resource_type="user",
            resource_id=current_user.id, ip_address=ip, user_agent=ua, success=False,
            details={"reason": "account_locked"},
        )
        db.commit()
        raise APIError(
            status.HTTP_429_TOO_MANY_REQUESTS, "Account locked due to too many failed password attempts",
            ErrorCode.ACCOUNT_LOCKED, headers={"Retry-After": str(retry_after)},
        )

    if not verify_password(payload.current_password, current_user.hashed_password):
        account_lockout.record_failed_password(db, current_user, ip, ua)
        log_event(
            db, "password_change_failed", user_id=current_user.id, resource_type="user",
            resource_id=current_user.id, ip_address=ip, user_agent=ua, success=False,
            details={"reason": "password_incorrect"},
        )
        db.commit()
        raise APIError(status.HTTP_403_FORBIDDEN, "Password is incorrect", ErrorCode.PASSWORD_INCORRECT)

    if payload.new_password == payload.current_password:
        raise APIError(
            status.HTTP_400_BAD_REQUEST, "New password must differ from the current one",
            ErrorCode.PASSWORD_UNCHANGED,
        )

    current_user.hashed_password = get_password_hash(payload.new_password)
    current_user.failed_login_attempts = 0
    log_event(
        db, "password_changed", user_id=current_user.id, resource_type="user",
        resource_id=current_user.id, ip_address=ip, user_agent=ua,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _require_reset_code(db: Session, user: User, code: Optional[str], ip: Optional[str], ua: Optional[str]) -> None:
    """Re-enrolment guard (services/face_reset_code.py): checks the code
    before Module 3 is called. A wrong code uses up one attempt."""
    if not code:
        raise APIError(
            status.HTTP_403_FORBIDDEN, "A reset code from your instructor is needed to replace your face",
            ErrorCode.FACE_RESET_CODE_REQUIRED,
        )
    try:
        result = face_reset_code.check(user.id, code)
    except face_reset_code.ResetCodeUnavailable:
        raise APIError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Face reset codes are temporarily unavailable",
            ErrorCode.FACE_RESET_CODE_UNAVAILABLE,
        )
    if result == face_reset_code.CheckStatus.OK:
        return
    log_event(
        db, "face_reset_code_rejected", user_id=user.id, resource_type="user", resource_id=user.id,
        ip_address=ip, user_agent=ua, success=False, details={"reason": result.value},
    )
    if result == face_reset_code.CheckStatus.BURNED:
        log_security_violation(
            db, "face_reset_code_guessing", user_id=user.id, resource_type="user", resource_id=user.id,
            ip_address=ip, user_agent=ua,
        )
    db.commit()
    raise APIError(status.HTTP_403_FORBIDDEN, "Reset code is invalid or expired", ErrorCode.FACE_RESET_CODE_INVALID)


@router.post("/me/face/enroll", response_model=FaceEnrollResponse)
def enroll_face(
    payload: FaceEnrollRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.camera_consent:
        raise APIError(
            status.HTTP_400_BAD_REQUEST, "Camera consent required before face enrollment",
            ErrorCode.CAMERA_CONSENT_REQUIRED,
        )

    require_image_size(payload.image)
    ip, ua = get_client_ip(request), request.headers.get("user-agent")
    # Replacing an enrolled face needs an instructor's one-time code; the
    # first enrolment doesn't.
    reenrolling = bool(current_user.face_enrolled) and settings.FACE_REENROLL_REQUIRES_CODE
    if reenrolling:
        _require_reset_code(db, current_user, payload.reset_code, ip, ua)

    user_id, consent = current_user.id, current_user.camera_consent
    # Don't hold a DB connection while Module 3 works (see the same step in
    # routers/checkins.py create_checkin). Nothing is pending here.
    db.commit()
    result = face_client.enroll_face(user_id, payload.image, consent)
    if result is None:
        # Module 3 timed out / errored / answered 4xx or 5xx - degrade to a
        # real 503, not a crash or a fake success.
        raise APIError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Face recognition service unavailable",
            ErrorCode.FACE_SERVICE_UNAVAILABLE,
        )
    if not result.get("enrollment_successful", False):
        raise APIError(status.HTTP_400_BAD_REQUEST, "No face detected in image", ErrorCode.NO_FACE_DETECTED)

    details = None
    if reenrolling:
        # Only now is the code used up, so a failed photo doesn't waste it.
        # Atomic: of two enrolments racing with one code, only one saves.
        try:
            issued_by = face_reset_code.consume(user_id, payload.reset_code)
        except face_reset_code.ResetCodeUnavailable:
            raise APIError(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Face reset codes are temporarily unavailable",
                ErrorCode.FACE_RESET_CODE_UNAVAILABLE,
            )
        if issued_by is None:
            raise APIError(
                status.HTTP_403_FORBIDDEN, "Reset code is invalid or expired", ErrorCode.FACE_RESET_CODE_INVALID
            )
        details = {"code_issued_by": issued_by}

    current_user.face_embedding_hash = result.get("face_template_hash")
    current_user.face_enrolled = True
    log_event(
        db, "face_reenrolled" if reenrolling else "face_enrolled", user_id=current_user.id, resource_type="user",
        resource_id=current_user.id, ip_address=ip, user_agent=ua, details=details,
    )
    db.commit()

    return FaceEnrollResponse(
        success=True,
        message="Face enrolled successfully",
        face_enrolled=True,
        quality_score=result.get("quality_score", 0.0),
    )


@router.post(
    "/{student_id}/face/reset-code", response_model=FaceResetCodeResponse, status_code=status.HTTP_201_CREATED
)
def issue_face_reset_code(
    student_id: str,
    request: Request,
    response: Response,
    current_user: User = Depends(require_role("instructor", "admin")),
    db: Session = Depends(get_db),
):
    """One-time code that lets this student replace their enrolled face.
    Team decision 2026-10-27: an instructor of one of the student's courses
    (who checks the student in person), or an admin. Not TAs."""
    student = db.get(User, student_id)
    # One answer for missing / not a student / deactivated, so this doesn't
    # reveal which accounts exist.
    if student is None or student.role != "student" or not student.is_active:
        raise APIError(status.HTTP_404_NOT_FOUND, "Student not found", ErrorCode.STUDENT_NOT_FOUND)
    if not teaches_student(db, current_user, student.id):
        raise APIError(
            status.HTTP_403_FORBIDDEN, "Not an instructor of this student", ErrorCode.INSUFFICIENT_PERMISSIONS
        )
    if not student.face_enrolled:
        raise APIError(
            status.HTTP_400_BAD_REQUEST, "Student has no enrolled face; they can enrol without a code",
            ErrorCode.FACE_NOT_ENROLLED,
        )

    try:
        issued = face_reset_code.issue(student.id, current_user.id)
    except face_reset_code.ResetCodeUnavailable:
        raise APIError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Face reset codes are temporarily unavailable",
            ErrorCode.FACE_RESET_CODE_UNAVAILABLE,
        )
    # Never the code itself.
    log_event(
        db, "face_reset_code_issued", user_id=current_user.id, resource_type="user", resource_id=student.id,
        ip_address=get_client_ip(request), user_agent=request.headers.get("user-agent"),
        details={"expires_at": issued.expires_at.isoformat()},
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return FaceResetCodeResponse(student_id=student.id, code=issued.code, expires_at=issued.expires_at)


@router.get("/", response_model=Page[UserResponse])
def list_users(
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = Query(default=50, ge=1),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    limit = page_limit(limit)
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if search:
        like = f"%{search}%"
        query = query.filter((User.full_name.ilike(like)) | (User.email.ilike(like)))

    total = query.count()
    users = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    return Page(items=users, total=total, limit=limit, offset=offset)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "User not found", ErrorCode.USER_NOT_FOUND)

    if current_user.role != "admin" and current_user.id != user.id:
        if current_user.role != "instructor":
            raise APIError(status.HTTP_403_FORBIDDEN, "Not authorized to view this user", ErrorCode.INSUFFICIENT_PERMISSIONS)
        # Instructor may view a user only if that user is an active
        # student in a course the instructor owns.
        # Same ownership rule as services/authz.py: a course with no
        # instructor_id assigned yet is visible to any instructor, not
        # just nobody - see routers/stats.py's student_stats for the
        # same fix applied after this exact pattern 403'd
        # test_stats_student on an unassigned test_course.
        if not teaches_student(db, current_user, user.id):
            raise APIError(status.HTTP_403_FORBIDDEN, "Not authorized to view this user", ErrorCode.INSUFFICIENT_PERMISSIONS)

    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UserAdminUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "User not found", ErrorCode.USER_NOT_FOUND)

    updates = drop_nulls_for_required(User, payload.model_dump(exclude_unset=True))
    for field, value in updates.items():
        setattr(user, field, value)

    log_event(db, "user_updated", user_id=current_user.id, resource_type="user", resource_id=user.id, details=updates)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", response_model=AccountDeletionResponse, status_code=status.HTTP_202_ACCEPTED)
def delete_user(user_id: str, current_user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    """Admin version of DELETE /users/me (no password; the admin is recorded as the actor)."""
    user = db.get(User, user_id)
    if user is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "User not found", ErrorCode.USER_NOT_FOUND)
    return _schedule_deletion(db, user, actor_id=current_user.id)
