"""
Device management - see API-SPECIFICATION.md's "Devices" section and
IMPLEMENTATION-PLAN.md's Phase 5.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.core.errors import APIError, ErrorCode
from app.db.models.device import Device
from app.db.models.user import User
from app.schemas.common import Page
from app.schemas.device import DeviceRegisterRequest, DeviceResponse, DeviceUpdateRequest
from app.services.audit import log_event
from app.services.sanitize import sanitize_text

router = APIRouter(prefix="/devices", tags=["devices"])


def _register(payload: DeviceRegisterRequest, current_user: User, db: Session) -> tuple[Device, bool]:
    """Shared body for POST /devices/register and POST /devices/ (the
    conftest.py test_device fixture tries the plural form first, falling
    back to /register - both exist and do the same thing).

    Returns (device, created) - created=False means this fingerprint was
    already registered to this same user and got refreshed instead of
    duplicated (the DB has a UNIQUE constraint on device_fingerprint, so a
    naive re-register would otherwise 500 on conflict)."""
    existing = db.query(Device).filter(Device.device_fingerprint == payload.device_fingerprint).first()
    if existing is not None:
        if existing.user_id != current_user.id:
            raise APIError(
                status.HTTP_400_BAD_REQUEST,
                "Device fingerprint already registered to another user",
                ErrorCode.DEVICE_FINGERPRINT_TAKEN,
            )
        existing.device_name = sanitize_text(payload.device_name) if payload.device_name else existing.device_name
        existing.platform = payload.platform or existing.platform
        existing.browser = payload.browser or existing.browser
        existing.os_version = payload.os_version or existing.os_version
        existing.app_version = payload.app_version or existing.app_version
        existing.last_seen_at = datetime.now(timezone.utc)
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return existing, False

    device = Device(
        user_id=current_user.id,
        device_fingerprint=payload.device_fingerprint,
        device_name=sanitize_text(payload.device_name) if payload.device_name else None,
        platform=payload.platform,
        browser=payload.browser,
        os_version=payload.os_version,
        app_version=payload.app_version,
        public_key=payload.public_key,
        public_key_created_at=datetime.now(timezone.utc) if payload.public_key else None,
    )
    db.add(device)
    db.flush()
    log_event(
        db, "device_registered", user_id=current_user.id, resource_type="device", resource_id=device.id,
        details={"platform": payload.platform},
    )
    db.commit()
    db.refresh(device)
    return device, True


@router.post("/register", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def register_device(
    payload: DeviceRegisterRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device, created = _register(payload, current_user, db)
    # status_code= on the decorator is just the default for the common
    # case; a re-register of the caller's own fingerprint updates in place
    # rather than creating, so report 200 for that, not a misleading 201.
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return device


@router.post("/", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def register_device_alias(
    payload: DeviceRegisterRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device, created = _register(payload, current_user, db)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return device


@router.get("/my-devices", response_model=list[DeviceResponse])
def my_devices(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(Device)
        .filter(Device.user_id == current_user.id)
        .order_by(Device.first_seen_at.desc())
        .all()
    )


@router.get("/", response_model=Page[DeviceResponse])
def list_devices(
    user_id: Optional[str] = None,
    is_trusted: Optional[bool] = None,
    is_active: Optional[bool] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    query = db.query(Device)
    if user_id:
        query = query.filter(Device.user_id == user_id)
    if is_trusted is not None:
        query = query.filter(Device.is_trusted == is_trusted)
    if is_active is not None:
        query = query.filter(Device.is_active == is_active)

    total = query.count()
    devices = query.order_by(Device.first_seen_at.desc()).offset(offset).limit(limit).all()
    return Page(items=devices, total=total, limit=limit, offset=offset)


@router.patch("/{device_id}", response_model=DeviceResponse)
def update_device(
    device_id: str,
    payload: DeviceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.get(Device, device_id)
    if device is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Device not found", ErrorCode.DEVICE_NOT_FOUND)

    is_owner = device.user_id == current_user.id
    is_admin = current_user.role == "admin"
    if not is_owner and not is_admin:
        raise APIError(status.HTTP_403_FORBIDDEN, "Not authorized for this device", ErrorCode.INSUFFICIENT_PERMISSIONS)

    updates = {}
    if payload.device_name is not None:
        device.device_name = sanitize_text(payload.device_name)
        updates["device_name"] = device.device_name
    if payload.is_active is not None:
        device.is_active = payload.is_active
        updates["is_active"] = payload.is_active
        if not payload.is_active:
            device.revoked_at = datetime.now(timezone.utc)
            device.revocation_reason = "deactivated by owner" if is_owner and not is_admin else "deactivated by admin"
    if payload.is_trusted is not None:
        if not is_admin:
            pass  # admin-only field - silently ignored for a non-admin caller
        else:
            device.is_trusted = payload.is_trusted
            device.trust_score = "high" if payload.is_trusted else "low"
            updates["is_trusted"] = payload.is_trusted

    if updates:
        log_event(
            db, "device_updated", user_id=current_user.id, resource_type="device", resource_id=device.id,
            details=updates,
        )
    db.commit()
    db.refresh(device)
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = db.get(Device, device_id)
    if device is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Device not found", ErrorCode.DEVICE_NOT_FOUND)

    is_owner = device.user_id == current_user.id
    is_admin = current_user.role == "admin"
    if not is_owner and not is_admin:
        raise APIError(status.HTTP_403_FORBIDDEN, "Not authorized for this device", ErrorCode.INSUFFICIENT_PERMISSIONS)

    # Soft-delete (revoke), matching the is_active/revoked_at/
    # revocation_reason columns DATABASE-SCHEMA.md defines for exactly
    # this, and the soft-delete convention used everywhere else in this
    # backend (users, courses, enrollments).
    device.is_active = False
    device.revoked_at = datetime.now(timezone.utc)
    device.revocation_reason = "removed by owner" if is_owner and not is_admin else "removed by admin"
    log_event(db, "device_removed", user_id=current_user.id, resource_type="device", resource_id=device.id)
    db.commit()
