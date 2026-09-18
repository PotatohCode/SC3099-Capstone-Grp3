"""
Shared FastAPI dependencies: DB session, current-user resolution, RBAC.

401 vs 403 (per IMPLEMENTATION-PLAN.md's pitfalls list): missing/invalid/
expired token -> 401 via get_current_user; valid token but wrong role -> 403
via require_role(). Never rely on the frontend to have hidden a button.
"""
from typing import Generator, Optional

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import APIError, ErrorCode
from app.core.security import decode_token
from app.db.base import SessionLocal
from app.db.models.user import User
from app.services.rate_limit import enforce_rate_limit

# auto_error=False so a missing Authorization header reaches our own 401
# handling below, instead of HTTPBearer's default (which raises 403 for a
# missing header but 401 for a malformed one - inconsistent with the rule
# above).
bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = APIError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        code=ErrorCode.INVALID_TOKEN,
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise unauthorized

    if payload.get("type") != "access":
        raise unauthorized

    user_id = payload.get("sub")
    if not user_id:
        raise unauthorized

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized

    # API-wide rate limit (1000/hour per user, Task 2.6) - enforced here
    # since nearly every protected route already depends on get_current_user,
    # rather than wiring it into each router individually.
    settings = get_settings()
    enforce_rate_limit(f"rate_limit:{user.id}:api", settings.RATE_LIMIT_API_PER_HOUR, 3600)

    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Like get_current_user, but returns None instead of 401 when there's
    no/invalid token - for endpoints that are readable anonymously but
    behave differently for a logged-in caller (e.g. GET /courses/'s
    instructor_id filter). tests/public/test_performance.py's list-latency
    and pagination checks call GET /courses/ with no Authorization header
    at all and expect 200, confirming this endpoint is meant to be public."""
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        return None
    if payload.get("type") != "access":
        return None
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        return None
    return user


def require_role(*roles: str):
    """Dependency factory: `Depends(require_role("admin", "instructor"))`."""

    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise APIError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
                code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            )
        return current_user

    return _dependency
