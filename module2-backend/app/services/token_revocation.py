"""
JWT revocation (logout). Tokens are stateless, so "logging out" means
remembering the token's unique id (`jti`) as revoked until the token would
have expired anyway: a Redis key `revoked_jti:{jti}` with that TTL.

Checked on every authenticated request (one Redis EXISTS) and on refresh.
Fails open if Redis is unavailable - same policy as rate limiting: an
outage shouldn't log everyone out. Tokens issued before jti existed have
none and can't be revoked; they simply expire as before.
"""
import logging
import time
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
