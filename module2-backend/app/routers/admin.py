"""
Admin endpoints required for automated test setup (API-SPECIFICATION.md's
"Admin Endpoints (Required for Automated Testing)" section) - these exist so
tests can seed/manipulate state without direct DB access, not just for the
Observability test category.

Every route here requires admin role (401 on bad/missing token via
get_current_user, 403 on a valid non-admin token via require_role).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_role
from app.core.security import get_password_hash
from app.db.models.course import Course
from app.db.models.enrollment import Enrollment
from app.db.models.session import ClassSession
from app.db.models.user import User
from app.schemas.admin import (
    AdminSessionStatusResponse,
    AdminSessionStatusUpdate,
    AdminUserBulkCreate,
    AdminUserBulkErrorItem,
    AdminUserBulkResponse,
    AdminUserBulkResultItem,
    AdminUserStatusResponse,
)
from app.schemas.enrollment import EnrollmentCreate, EnrollmentResponse
from app.services.audit import log_event
from app.services.sanitize import sanitize_text

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role("admin"))])


@router.patch("/users/{user_id}/deactivate", response_model=AdminUserStatusResponse)
def deactivate_user(user_id: str, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = False
    log_event(db, "user_updated", user_id=user.id, resource_type="user", resource_id=user.id,
              details={"is_active": False})
    db.commit()

    return AdminUserStatusResponse(
        id=user.id, email=user.email, is_active=False, message="User deactivated successfully"
    )


@router.patch("/users/{user_id}/activate", response_model=AdminUserStatusResponse)
def activate_user(user_id: str, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = True
    log_event(db, "user_updated", user_id=user.id, resource_type="user", resource_id=user.id,
              details={"is_active": True})
    db.commit()

    return AdminUserStatusResponse(
        id=user.id, email=user.email, is_active=True, message="User activated successfully"
    )


@router.post("/users/bulk", response_model=AdminUserBulkResponse, status_code=status.HTTP_201_CREATED)
def bulk_create_users(payload: AdminUserBulkCreate, db: Session = Depends(get_db)):
    created: list[User] = []
    errors: list[AdminUserBulkErrorItem] = []

    for item in payload.users:
        if db.query(User).filter(User.email == item.email).first() is not None:
            errors.append(AdminUserBulkErrorItem(email=item.email, error="Email already registered"))
            continue

        user = User(
            email=item.email,
            full_name=sanitize_text(item.full_name),
            hashed_password=get_password_hash(item.password),
            role=item.role,
        )
        db.add(user)
        db.flush()
        log_event(db, "user_created", user_id=user.id, resource_type="user", resource_id=user.id)
        created.append(user)

    db.commit()
    for user in created:
        db.refresh(user)

    return AdminUserBulkResponse(
        created=len(created),
        failed=len(errors),
        users=[
            AdminUserBulkResultItem(id=u.id, email=u.email, full_name=u.full_name, role=u.role)
            for u in created
        ],
        errors=errors,
    )


@router.patch("/sessions/{session_id}/status", response_model=AdminSessionStatusResponse)
def update_session_status(
    session_id: str, payload: AdminSessionStatusUpdate, db: Session = Depends(get_db)
):
    session_obj = db.get(ClassSession, session_id)
    if session_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    old_status = session_obj.status
    session_obj.status = payload.status
    log_event(
        db, "session_updated", resource_type="session", resource_id=session_obj.id,
        details={"old_status": old_status, "new_status": payload.status},
    )
    db.commit()
    db.refresh(session_obj)

    return AdminSessionStatusResponse(
        id=session_obj.id,
        name=session_obj.name,
        status=session_obj.status,
        message=f"Session status changed from '{old_status}' to '{session_obj.status}'",
    )


@router.post("/enrollments/", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED)
def admin_create_enrollment(payload: EnrollmentCreate, db: Session = Depends(get_db)):
    if db.get(User, payload.student_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    if db.get(Course, payload.course_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    existing = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == payload.student_id, Enrollment.course_id == payload.course_id)
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Student already enrolled")

    enrollment = Enrollment(student_id=payload.student_id, course_id=payload.course_id)
    db.add(enrollment)
    db.flush()
    log_event(
        db, "enrollment_added", resource_type="enrollment", resource_id=enrollment.id,
        details={"student_id": payload.student_id, "course_id": payload.course_id},
    )
    db.commit()
    db.refresh(enrollment)
    return enrollment
