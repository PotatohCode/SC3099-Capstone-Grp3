"""
One-time codes for replacing an enrolled face (team decision 2026-10-27).

Without them, anyone who knows a student's password could enrol their own
face on that account, and the face match would then pass for them. So once
a face is enrolled, POST /users/me/face/enroll needs a code that an
instructor of one of the student's courses (or an admin) generated after
seeing the student in person. Each code is:

- bound to one student: useless on any other account;
- single use, and replaced when a new one is issued;
- short lived (FACE_RESET_CODE_TTL_SECONDS);
- burned after FACE_RESET_CODE_MAX_ATTEMPTS wrong guesses.

The enrol endpoint checks the code before calling Module 3 and consumes it
only after a successful enrolment, so a "no face detected" photo doesn't
waste it. Consuming is atomic: of two enrolments racing with one code, only
one saves.

Redis key (with a TTL): `face_reset_code:{student_id}` -> hash of
`code_hash` (SHA-256, the code itself is never stored), `issued_by`,
`attempts` (wrong guesses so far).

Redis down: issuing and re-enrolling fail with 503; a first enrolment
doesn't touch Redis and still works.
"""
import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

import redis

from app.core.config import get_settings
from app.services.rate_limit import _get_client

logger = logging.getLogger("saiv.face_reset_code")

_KEY = "face_reset_code:{}"
# No 0/O, 1/I/L: the code is read out loud and typed on a phone.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8

# Wrong guess: count it, and burn the code on the last allowed one. Atomic,
# so parallel guesses can't get more than the allowed number of tries.
# Returns: 0 no code, 1 correct, 2 wrong, 3 wrong and now burned.
_CHECK_SCRIPT = """
local stored = redis.call('HGET', KEYS[1], 'code_hash')
if not stored then return 0 end
if stored == ARGV[1] then return 1 end
local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
if attempts >= tonumber(ARGV[2]) then
  redis.call('DEL', KEYS[1])
  return 3
end
return 2
"""

# Take the code if it still matches; returns the issuer, or false.
_CONSUME_SCRIPT = """
local stored = redis.call('HGET', KEYS[1], 'code_hash')
if stored and stored == ARGV[1] then
  local issuer = redis.call('HGET', KEYS[1], 'issued_by')
  redis.call('DEL', KEYS[1])
  return issuer
end
return false
"""


class ResetCodeUnavailable(Exception):
    """Redis couldn't be reached."""


def normalize(code: str) -> str:
    """Case-insensitive; spaces and hyphens ignored (`k7qm-4xpa` == `K7QM4XPA`)."""
    return "".join(ch for ch in code.upper() if ch not in " -\t")


def _hash(code: str) -> str:
    return hashlib.sha256(normalize(code).encode()).hexdigest()


def format_code(raw: str) -> str:
    """`K7QM4XPA` -> `K7QM-4XPA`, easier to read out."""
    return f"{raw[:4]}-{raw[4:]}"


@dataclass
class IssuedCode:
    code: str
    expires_at: datetime


def issue(student_id: str, issued_by: str) -> IssuedCode:
    """A new code for this student, replacing any earlier one."""
    settings = get_settings()
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    key = _KEY.format(student_id)
    ttl = settings.FACE_RESET_CODE_TTL_SECONDS
    try:
        pipe = _get_client().pipeline()
        pipe.delete(key)
        pipe.hset(key, mapping={"code_hash": _hash(raw), "issued_by": issued_by, "attempts": 0})
        pipe.expire(key, ttl)
        pipe.execute()
    except redis.RedisError as exc:
        logger.warning("Redis unavailable; could not issue face reset code")
        raise ResetCodeUnavailable from exc
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=ttl)
    return IssuedCode(code=format_code(raw), expires_at=expires_at)


class CheckStatus(str, Enum):
    OK = "ok"
    INVALID = "invalid"  # no live code for this student (none, expired, used or burned)
    WRONG = "wrong"  # doesn't match; attempts left
    BURNED = "burned"  # doesn't match, and that was the last attempt


def check(student_id: str, code: str) -> CheckStatus:
    """Checks without consuming. A wrong code uses up one attempt."""
    if not normalize(code):
        return CheckStatus.INVALID
    try:
        result = _get_client().eval(
            _CHECK_SCRIPT, 1, _KEY.format(student_id), _hash(code), get_settings().FACE_RESET_CODE_MAX_ATTEMPTS
        )
    except redis.RedisError as exc:
        logger.warning("Redis unavailable; could not check face reset code")
        raise ResetCodeUnavailable from exc
    return {0: CheckStatus.INVALID, 1: CheckStatus.OK, 2: CheckStatus.WRONG}.get(int(result), CheckStatus.BURNED)


def consume(student_id: str, code: str) -> Optional[str]:
    """Takes the code; returns who issued it, or None if it's no longer valid
    (used by a parallel enrolment, replaced, or expired meanwhile)."""
    try:
        issuer = _get_client().eval(_CONSUME_SCRIPT, 1, _KEY.format(student_id), _hash(code))
    except redis.RedisError as exc:
        logger.warning("Redis unavailable; could not consume face reset code")
        raise ResetCodeUnavailable from exc
    return issuer or None
