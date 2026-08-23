from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.db.models.user import User
from app.schemas.user import UserResponse, UserUpdateRequest
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
