"""
Server-issued liveness challenges (POST /checkins/challenge).

A fixed "always blink" challenge can be beaten with a pre-recorded video.
Here the backend picks a random sequence of actions (e.g. blink, then turn
left), the student performs it while the app captures a frame burst, and
Module 3 checks the frames against the sequence. Each challenge is:

- single use: consumed atomically (GETDEL) by the check-in that names it;
- bound to one student and one session;
- short lived (LIVENESS_CHALLENGE_TTL_SECONDS).

Stored in Redis only (`liveness_challenge:{id}` -> JSON). A short-lived
`liveness_challenge_used:{id}` marker tells "used twice" (a replay attempt,
audited) apart from "expired" (just fetch a new one).

Redis down: issuing fails (503, the app can fall back to a plain check-in);
consuming returns UNAVAILABLE, which the check-in treats as unverified
rather than rejecting a genuine student.
"""
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional

import redis

from app.core.config import get_settings
from app.services.rate_limit import _get_client

logger = logging.getLogger("saiv.liveness_challenge")

_KEY = "liveness_challenge:{}"
_USED_KEY = "liveness_challenge_used:{}"
_USED_MARKER_SECONDS = 3600
_rng = secrets.SystemRandom()


class ChallengeUnavailable(Exception):
    """Redis couldn't store the challenge."""


def generate_sequence(actions: List[str], steps: int) -> List[str]:
    """`steps` random actions, never the same one twice in a row."""
    sequence: List[str] = []
    for _ in range(steps):
        choices = [a for a in actions if not sequence or a != sequence[-1]] or actions
        sequence.append(_rng.choice(choices))
    return sequence


@dataclass
class IssuedChallenge:
    challenge_id: str
    sequence: List[str]
    expires_at: datetime


def issue(student_id: str, session_id: str) -> IssuedChallenge:
    settings = get_settings()
    challenge_id = secrets.token_urlsafe(24)
    sequence = generate_sequence(settings.LIVENESS_CHALLENGE_ACTIONS, settings.LIVENESS_CHALLENGE_STEPS)
    ttl = settings.LIVENESS_CHALLENGE_TTL_SECONDS
    record = {"student_id": student_id, "session_id": session_id, "sequence": sequence}
    try:
        _get_client().set(_KEY.format(challenge_id), json.dumps(record), ex=ttl)
    except redis.RedisError as exc:
        logger.warning("Redis unavailable; could not issue liveness challenge")
        raise ChallengeUnavailable from exc
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=ttl)
    return IssuedChallenge(challenge_id=challenge_id, sequence=sequence, expires_at=expires_at)


class ConsumeStatus(str, Enum):
    OK = "ok"
    INVALID = "invalid"  # unknown or expired
    REUSED = "reused"  # already consumed once
    OTHER_STUDENT = "other_student"  # issued to someone else
    WRONG_SESSION = "wrong_session"  # this student's, but for another session
    UNAVAILABLE = "unavailable"  # Redis down


@dataclass
class ConsumeResult:
    status: ConsumeStatus
    sequence: Optional[List[str]] = None


def consume(challenge_id: str, student_id: str, session_id: str) -> ConsumeResult:
    """Atomically takes the challenge, so it can never be used twice - even
    when the check-in that names it then fails, or names the wrong session."""
    client = _get_client()
    try:
        raw = client.getdel(_KEY.format(challenge_id))
        if raw is None:
            reused = bool(client.exists(_USED_KEY.format(challenge_id)))
            return ConsumeResult(ConsumeStatus.REUSED if reused else ConsumeStatus.INVALID)
        client.set(_USED_KEY.format(challenge_id), "1", ex=_USED_MARKER_SECONDS)
    except redis.RedisError:
        logger.warning("Redis unavailable; could not verify liveness challenge")
        return ConsumeResult(ConsumeStatus.UNAVAILABLE)

    record = json.loads(raw)
    if record.get("student_id") != student_id:
        return ConsumeResult(ConsumeStatus.OTHER_STUDENT)
    if record.get("session_id") != session_id:
        return ConsumeResult(ConsumeStatus.WRONG_SESSION)
    return ConsumeResult(ConsumeStatus.OK, sequence=list(record.get("sequence") or []))
