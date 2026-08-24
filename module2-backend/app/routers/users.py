from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.core.errors import APIError, ErrorCode
from app.db.models.course import Course
from app.db.models.enrollment import Enrollment
from app.db.models.user import User
from app.schemas.common import Page
from app.schemas.user import UserAdminUpdate, UserResponse, UserUpdateRequest
from app.services.audit import log_event
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
        is_their_student = (
            db.query(Enrollment)
            .join(Course, Enrollment.course_id == Course.id)
            .filter(
                Enrollment.student_id == user.id,
                Enrollment.is_active.is_(True),
                Course.instructor_id == current_user.id,
            )
            .first()
            is not None
        )
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
