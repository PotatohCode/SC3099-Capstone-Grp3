from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_db
from app.core.errors import APIError, ErrorCode
from app.core.metrics import login_failed_total
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.db.models.user import User
from app.schemas.auth import LoginRequest, LoginResponse, RefreshRequest, RefreshResponse, RegisterRequest
from app.schemas.user import UserResponse
from app.services.audit import log_event
from app.services.rate_limit import enforce_rate_limit, peek_rate_limit, record_hit
from app.services.sanitize import sanitize_text

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    if ip:
        enforce_rate_limit(f"rate_limit:{ip}:register", settings.RATE_LIMIT_REGISTRATION_PER_HOUR, 3600)

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing is not None:
        raise APIError(status.HTTP_400_BAD_REQUEST, "Email already registered", ErrorCode.EMAIL_ALREADY_REGISTERED)

    user = User(
        email=payload.email,
        full_name=sanitize_text(payload.full_name),
        hashed_password=get_password_hash(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.flush()  # populate user.id (Python-side default) for the audit row below

    log_event(
        db,
        "user_created",
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip, ua = _client_ip(request), request.headers.get("user-agent")
    login_key = f"rate_limit:{ip}:login"
    if ip:
        # Peek, don't count yet - only failed attempts count toward this
        # limit (see services/rate_limit.py's peek_rate_limit docstring
        # for why: it's a brute-force guard, not a "many legit logins from
        # one IP" guard).
        allowed, retry_after = peek_rate_limit(login_key, settings.RATE_LIMIT_LOGIN_PER_HOUR)
        if not allowed:
            raise APIError(
                status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed login attempts", ErrorCode.RATE_LIMITED,
                headers={"Retry-After": str(retry_after)},
            )

    user = db.query(User).filter(User.email == payload.email).first()

    if user is None or not verify_password(payload.password, user.hashed_password):
        login_failed_total.inc()
        if ip:
            record_hit(login_key, 3600)
        log_event(
            db, "login_failed", user_id=user.id if user else None, ip_address=ip, user_agent=ua,
            success=False, details={"email": payload.email},
        )
        db.commit()
        raise APIError(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password", ErrorCode.INVALID_CREDENTIALS)

    if not user.is_active:
        login_failed_total.inc()
        if ip:
            record_hit(login_key, 3600)
        log_event(
            db, "login_failed", user_id=user.id, ip_address=ip, user_agent=ua,
            success=False, details={"reason": "account_disabled"},
        )
        db.commit()
        raise APIError(status.HTTP_403_FORBIDDEN, "Account disabled", ErrorCode.ACCOUNT_DISABLED)

    user.last_login_at = datetime.now(timezone.utc)
    log_event(db, "login_success", user_id=user.id, ip_address=ip, user_agent=ua)
    db.commit()
    db.refresh(user)

    return LoginResponse(
        access_token=create_access_token(user.id, user.email, user.role),
        refresh_token=create_refresh_token(user.id, user.email, user.role),
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    invalid = APIError(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token", ErrorCode.INVALID_REFRESH_TOKEN)

    try:
        token_payload = decode_token(payload.refresh_token)
    except JWTError:
        raise invalid

    if token_payload.get("type") != "refresh":
        raise invalid

    user = db.get(User, token_payload.get("sub"))
    if user is None or not user.is_active:
        raise invalid

    return RefreshResponse(
        access_token=create_access_token(user.id, user.email, user.role),
        refresh_token=create_refresh_token(user.id, user.email, user.role),
    )
