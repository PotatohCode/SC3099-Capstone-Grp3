from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.core.errors import APIError, ErrorCode
from app.db.models.course import Course
from app.db.models.enrollment import Enrollment
from app.db.models.user import User
from app.schemas.common import Page
from app.schemas.user import FaceEnrollRequest, FaceEnrollResponse, UserAdminUpdate, UserResponse, UserUpdateRequest
from app.services import face_client
from app.services.audit import log_event
from app.services.authz import can_edit_course
from app.services.sanitize import sanitize_text

router = APIRouter(prefix="/users", tags=["users"])


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


@router.post("/me/face/enroll", response_model=FaceEnrollResponse)
def enroll_face(
    payload: FaceEnrollRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.camera_consent:
        raise APIError(
            status.HTTP_400_BAD_REQUEST, "Camera consent required before face enrollment",
            ErrorCode.CAMERA_CONSENT_REQUIRED,
        )

    result = face_client.enroll_face(current_user.id, payload.image, current_user.camera_consent)
    if result is None:
        # Module 3 timed out / errored / is a 501 stub (see KNOWN-ISSUES.md) -
        # degrade to a real 503, not a crash or a fake success.
        raise APIError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Face recognition service unavailable",
            ErrorCode.FACE_SERVICE_UNAVAILABLE,
        )
    if not result.get("enrollment_successful", False):
        raise APIError(status.HTTP_400_BAD_REQUEST, "No face detected in image", ErrorCode.NO_FACE_DETECTED)

    current_user.face_embedding_hash = result.get("face_template_hash")
    current_user.face_enrolled = True
    log_event(db, "face_enrolled", user_id=current_user.id, resource_type="user", resource_id=current_user.id)
    db.commit()

    return FaceEnrollResponse(
        success=True,
        message="Face enrolled successfully",
        face_enrolled=True,
        quality_score=result.get("quality_score", 0.0),
    )


@router.get("/", response_model=Page[UserResponse])
def list_users(
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
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
        their_courses = (
            db.query(Course)
            .join(Enrollment, Enrollment.course_id == Course.id)
            .filter(Enrollment.student_id == user.id, Enrollment.is_active.is_(True))
            .all()
        )
        is_their_student = any(can_edit_course(current_user, c) for c in their_courses)
        if not is_their_student:
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

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(user, field, value)

    log_event(db, "user_updated", user_id=current_user.id, resource_type="user", resource_id=user.id, details=updates)
    db.commit()
    db.refresh(user)
    return user
