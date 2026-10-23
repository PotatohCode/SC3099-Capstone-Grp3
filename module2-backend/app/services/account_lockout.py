"""
Per-account lockout after too many wrong passwords (config
MAX_FAILED_LOGIN_ATTEMPTS / ACCOUNT_LOCKOUT_MINUTES; team decision:
10 failures lock the account for 15 min, 429 + Retry-After).

Shared by every endpoint that checks a password, so they all count toward
the same limit: POST /auth/login and POST /users/me/password. Without the
second, a stolen access token would allow unlimited password guesses.

Callers commit; nothing here does.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.metrics import account_lockouts_total
from app.db.models.user import User
from app.services.audit import log_event, log_security_violation


def _utcnow_naive() -> datetime:
    # users.locked_until is a naive DateTime column holding UTC - same
    # convention as checkins.py's _now().
    return datetime.now(timezone.utc).replace(tzinfo=None)


def locked_retry_after(db: Session, user: User) -> Optional[int]:
    """Seconds until the lock ends if the account is locked, else None.

    An expired lock is cleared here, so the account starts over with a
    fresh set of attempts. Flushed explicitly: record_failed_password's
    atomic UPDATE increments the DB value, so an unflushed reset would
    leave it at MAX and re-lock on the very next wrong password."""
    if user.locked_until is None:
        return None
    now = _utcnow_naive()
    if user.locked_until > now:
        return max(1, math.ceil((user.locked_until - now).total_seconds()))
    user.locked_until = None
    user.failed_login_attempts = 0
    db.flush()
    return None


def record_failed_password(
    db: Session, user: User, ip_address: Optional[str], user_agent: Optional[str]
) -> None:
    """Counts one wrong password and locks the account at the threshold
    (audited as account_locked + a security_violation)."""
    settings = get_settings()
    # Atomic increment so concurrent wrong-password requests can't
    # lose updates and slip past the threshold.
    attempts = db.execute(
        update(User)
        .where(User.id == user.id)
        .values(failed_login_attempts=User.failed_login_attempts + 1)
        .returning(User.failed_login_attempts)
    ).scalar_one()
    if attempts < settings.MAX_FAILED_LOGIN_ATTEMPTS:
        return
    # Conditional so that, of several parallel requests past the threshold,
    # exactly one sets the lock and audits it: the in-memory user is stale
    # under concurrency, but Postgres re-checks this WHERE after waiting
    # for the row lock held by the request that locked first.
    now = _utcnow_naive()
    locked = db.execute(
        update(User)
        .where(User.id == user.id, or_(User.locked_until.is_(None), User.locked_until <= now))
        .values(locked_until=now + timedelta(minutes=settings.ACCOUNT_LOCKOUT_MINUTES))
        .returning(User.id)
    ).scalar_one_or_none()
    if locked is not None:
        account_lockouts_total.inc()
        log_event(
            db, "account_locked", user_id=user.id, resource_type="user", resource_id=user.id,
            ip_address=ip_address, user_agent=user_agent, success=False,
            details={"failed_attempts": attempts, "lockout_minutes": settings.ACCOUNT_LOCKOUT_MINUTES},
        )
        log_security_violation(
            db, "account_lockout", user_id=user.id, resource_type="user", resource_id=user.id,
            ip_address=ip_address, user_agent=user_agent, details={"failed_attempts": attempts},
        )
