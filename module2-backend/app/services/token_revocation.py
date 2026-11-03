"""
JWT revocation (logout). Tokens are stateless, so "logging out" means
remembering the token's unique id (`jti`) as revoked until the token would
have expired anyway: a Redis key `revoked_jti:{jti}` with that TTL.

Checked on every authenticated request (one Redis EXISTS) and on refresh.
Fails open if Redis is unavailable - same policy as rate limiting: an
outage shouldn't log everyone out. Tokens issued before jti existed have
none and can't be revoked; they simply expire as before.

A password change ends the user's *other* sessions without Redis: the
users row records when (`tokens_valid_after`) and which session made it
(`kept_session_id`, the token's `sid` claim, shared by every token from
one login). See predates_password_change().
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import redis

from app.services.rate_limit import _get_client

logger = logging.getLogger("saiv.token_revocation")


def revoke(payload: dict[str, Any]) -> None:
    jti: Optional[str] = payload.get("jti")
    exp = payload.get("exp")
    if not jti or not exp:
        return
    ttl = int(exp - time.time())
    if ttl <= 0:
        return  # already expired, nothing to do
    try:
        _get_client().set(f"revoked_jti:{jti}", "1", ex=ttl)
    except redis.RedisError:
        logger.warning("Redis unavailable; could not record token revocation")


def is_revoked(payload: dict[str, Any]) -> bool:
    jti = payload.get("jti")
    if not jti:
        return False
    try:
        return bool(_get_client().exists(f"revoked_jti:{jti}"))
    except redis.RedisError:
        logger.warning("Redis unavailable; skipping token revocation check (fail open)")
        return False


def end_other_sessions(user, payload: dict[str, Any]) -> None:
    """After a password change: invalidate every token issued so far except
    the caller's session. Whole seconds, like the JWT `iat` claim. Tokens
    without `sid` (issued before it existed) count as other sessions."""
    user.tokens_valid_after = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    user.kept_session_id = payload.get("sid")


def predates_password_change(payload: dict[str, Any], user) -> bool:
    """True for a token from another session issued before the user's last
    password change. A token issued in the same second survives, so a login
    straight after the change always works."""
    cutoff = user.tokens_valid_after
    if cutoff is None:
        return False
    sid = payload.get("sid")
    if sid and sid == user.kept_session_id:
        return False
    return payload.get("iat", 0) < cutoff.replace(tzinfo=timezone.utc).timestamp()
