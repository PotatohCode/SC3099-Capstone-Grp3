import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, status
from jose import JWTError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_db
from app.core.errors import APIError, ErrorCode
from app.core.metrics import account_lockouts_total, login_failed_total
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
from app.services.client_ip import get_client_ip
from app.services.rate_limit import enforce_rate_limit, peek_rate_limit, record_hit
from app.services.sanitize import sanitize_text

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _utcnow_naive() -> datetime:
    # users.locked_until is a naive DateTime column holding UTC - same
    # convention as checkins.py's _now().
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
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
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip, ua = get_client_ip(request), request.headers.get("user-agent")
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

    # Per-account lockout - checked BEFORE the password, so a locked
    # account gets 429 even when the correct password is supplied (see
    # config.MAX_FAILED_LOGIN_ATTEMPTS for the requirement).
    if user is not None and user.locked_until is not None:
        now = _utcnow_naive()
        if user.locked_until > now:
            login_failed_total.inc()
            log_event(
                db, "login_failed", user_id=user.id, ip_address=ip, user_agent=ua,
                success=False, details={"reason": "account_locked"},
            )
            db.commit()
            raise APIError(
                status.HTTP_429_TOO_MANY_REQUESTS, "Account locked due to too many failed login attempts",
                ErrorCode.ACCOUNT_LOCKED,
                headers={"Retry-After": str(max(1, math.ceil((user.locked_until - now).total_seconds())))},
            )
        # Lock expired - the account starts over with a fresh set of attempts.
        # Flush explicitly: the atomic UPDATE below increments the DB value,
        # so an unflushed reset would leave it at MAX and re-lock on the very
        # next wrong password.
        user.locked_until = None
        user.failed_login_attempts = 0
        db.flush()

    if user is None or not verify_password(payload.password, user.hashed_password):
        login_failed_total.inc()
        if ip:
            record_hit(login_key, 3600)
        if user is not None:
            # Atomic increment so concurrent wrong-password requests can't
            # lose updates and slip past the threshold.
            attempts = db.execute(
                update(User)
                .where(User.id == user.id)
                .values(failed_login_attempts=User.failed_login_attempts + 1)
                .returning(User.failed_login_attempts)
            ).scalar_one()
            if attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS and user.locked_until is None:
                user.locked_until = _utcnow_naive() + timedelta(minutes=settings.ACCOUNT_LOCKOUT_MINUTES)
                account_lockouts_total.inc()
                log_event(
                    db, "account_locked", user_id=user.id, resource_type="user", resource_id=user.id,
                    ip_address=ip, user_agent=ua, success=False,
                    details={"failed_attempts": attempts, "lockout_minutes": settings.ACCOUNT_LOCKOUT_MINUTES},
                )
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
    user.failed_login_attempts = 0
    user.locked_until = None
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
