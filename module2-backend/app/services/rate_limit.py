"""
Redis-backed rate limiting (Task 2.6 / SECURITY-REQUIREMENTS.md). Key
convention: `rate_limit:{identifier}:{action_label}` (e.g.
`rate_limit:192.168.1.1:login`, `rate_limit:{user_id}:checkin`).

Deviates from IMPLEMENTATION-PLAN.md's cheat-sheet sample in one way:
uses `expire(key, window, nx=True)` instead of an unconditional
`expire()` on every hit. The unconditional version (the doc's literal
sample, copied from SECURITY-REQUIREMENTS.md) resets the TTL on every
request, so a steady stream of requests never lets the key expire - it's
actually a sliding window that can block forever under sustained
traffic, not the fixed window the "N per window" language implies.
`nx=True` (only set the expiry if the key doesn't have one yet) gives a
real fixed window: it resets exactly `window` seconds after the FIRST
hit, not the most recent one. Needs Redis 7's `EXPIRE ... NX` support -
already satisfied by the `redis:7-alpine` image this project uses.

Fails open on Redis errors - a Redis outage degrades to "unenforced,"
not an outage of the whole API, same resilience philosophy as the Face
Service calls (see services/face_client.py).
"""
import logging
from typing import Optional, Tuple

import redis

from app.core.config import get_settings
from app.core.errors import APIError, ErrorCode

logger = logging.getLogger("saiv.rate_limit")

_client: Optional[redis.Redis] = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis.Redis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2.0, socket_timeout=2.0
        )
    return _client


def check_rate_limit(key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
    """Returns (allowed, retry_after_seconds) - retry_after is 0 when allowed."""
    try:
        client = _get_client()
        current = client.get(key)
        if current is not None and int(current) >= limit:
            ttl = client.ttl(key)
            return False, ttl if ttl and ttl > 0 else window_seconds

        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        pipe.execute()
        return True, 0
    except redis.RedisError as exc:
        logger.warning("Rate limit check failed for %s, failing open: %s", key, exc)
        return True, 0


def enforce_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    """Raises APIError(429) with a Retry-After header if the limit is hit.
    Every call both checks AND counts - use this when every call to the
    guarded action should count toward the limit (registration, check-in,
    the API-wide per-user limit). For login specifically, see
    peek_rate_limit()/record_hit() below instead."""
    allowed, retry_after = check_rate_limit(key, limit, window_seconds)
    if not allowed:
        raise APIError(
            429, "Rate limit exceeded", ErrorCode.RATE_LIMITED, headers={"Retry-After": str(retry_after)}
        )


def peek_rate_limit(key: str, limit: int) -> Tuple[bool, int]:
    """Read-only: checks whether `key` is already at/over `limit` WITHOUT
    incrementing. Pairs with record_hit() for actions where only certain
    outcomes should count toward the limit - login is the case this
    exists for: SECURITY-REQUIREMENTS.md's 60/hour login limit exists to
    stop brute-force password guessing (repeated *failed* attempts), not
    to punish an IP with many legitimate successful logins (e.g. a
    shared/NAT'd network). Counting every login regardless of outcome
    measurably breaks this: a full tests/public/ run made 163 login calls
    from one shared IP but only 33 were failures - comfortably under the
    spec's 60/hour once only failures count, whereas counting everything
    blew through it by 2.7x. Check with this before attempting the login,
    then call record_hit() only if it turns out to be a failure."""
    try:
        client = _get_client()
        current = client.get(key)
        if current is not None and int(current) >= limit:
            ttl = client.ttl(key)
            return False, ttl if ttl and ttl > 0 else 0
        return True, 0
    except redis.RedisError as exc:
        logger.warning("Rate limit peek failed for %s, failing open: %s", key, exc)
        return True, 0


def record_hit(key: str, window_seconds: int) -> None:
    """Increments the counter for `key`, starting the fixed window on the
    first hit (see the module docstring's `nx=True` note). Call after
    peek_rate_limit() only for outcomes that should count."""
    try:
        client = _get_client()
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        pipe.execute()
    except redis.RedisError as exc:
        logger.warning("Rate limit record_hit failed for %s, failing open: %s", key, exc)
