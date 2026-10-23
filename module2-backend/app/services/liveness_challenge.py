"""
Server-issued liveness challenges (POST /checkins/challenge) and retries
(POST /checkins/challenge/{id}/verify).

A fixed "always blink" challenge can be beaten with a pre-recorded video.
Here the backend picks a random sequence of actions (e.g. blink, then turn
left), the student performs it while the app captures a frame burst, and
Module 3 checks the frames against the sequence. Each challenge is:

- single use: consumed atomically by the verify or check-in that names it;
- bound to one student and one session;
- short lived (LIVENESS_CHALLENGE_TTL_SECONDS).

Retries: the app may verify a burst first and get an answer back. Each
verify uses up one of LIVENESS_MAX_ATTEMPTS per (student, session); a
retry needs a new challenge (new sequence). A pass is stored with the hash
of the verified burst (never the images), and the check-in must resend the
same burst for it to count. A spoof verdict ends the attempts. A Module 3
failure doesn't use up an attempt. The counter expires with the session's
check-in window.

Redis keys (all with a TTL):
- `liveness_challenge:{id}` -> issued, not yet used (JSON)
- `liveness_result:{id}` -> verified; `outcome` is null while Module 3 is
  still answering. Renamed from the key above, so two verifies of one
  challenge can't both run
- `liveness_challenge_used:{id}` -> marker telling "used twice" (a replay
  attempt, audited) apart from "expired" (just fetch a new one)
- `liveness_attempts:{student}:{session}` -> hash: used, failed, spoof

Redis down: issuing fails (503, the app can fall back to a plain check-in);
verifying answers "unverified" without using an attempt; consuming returns
UNAVAILABLE, which the check-in treats as unverified rather than rejecting
a genuine student.
"""
import calendar
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
_RESULT_KEY = "liveness_result:{}"
_USED_KEY = "liveness_challenge_used:{}"
_ATTEMPTS_KEY = "liveness_attempts:{}:{}"
_USED_MARKER_SECONDS = 3600
# The attempt counter outlives the check-in window a little, so a verify
# that finishes right at closing time still lands in the same counter.
_ATTEMPTS_MARGIN_SECONDS = 600
_rng = secrets.SystemRandom()


class ChallengeUnavailable(Exception):
    """Redis couldn't store the challenge."""


class AttemptsExhausted(Exception):
    """No liveness attempts left for this student and session."""


def generate_sequence(actions: List[str], steps: int) -> List[str]:
    """`steps` random actions, never the same one twice in a row."""
    sequence: List[str] = []
    for _ in range(steps):
        choices = [a for a in actions if not sequence or a != sequence[-1]] or actions
        sequence.append(_rng.choice(choices))
    return sequence


def _epoch(naive_utc: datetime) -> int:
    return calendar.timegm(naive_utc.timetuple())


@dataclass
class AttemptState:
    used: int = 0
    failed: int = 0
    spoof: bool = False

    @property
    def attempts_left(self) -> int:
        if self.spoof:
            return 0
        return max(0, get_settings().LIVENESS_MAX_ATTEMPTS - self.used)


def _read_state(client: redis.Redis, student_id: str, session_id: str) -> AttemptState:
    raw = client.hgetall(_ATTEMPTS_KEY.format(student_id, session_id)) or {}
    return AttemptState(
        used=int(raw.get("used", 0)), failed=int(raw.get("failed", 0)), spoof=raw.get("spoof") == "1"
    )


def attempt_state(student_id: str, session_id: str) -> Optional[AttemptState]:
    """This student's liveness attempts for the session; None if Redis is down."""
    try:
        return _read_state(_get_client(), student_id, session_id)
    except redis.RedisError:
        logger.warning("Redis unavailable; could not read liveness attempts")
        return None


@dataclass
class IssuedChallenge:
    challenge_id: str
    sequence: List[str]
    expires_at: datetime
    attempts_left: int


def issue(student_id: str, session_id: str, window_closes_at: datetime) -> IssuedChallenge:
    settings = get_settings()
    client = _get_client()
    challenge_id = secrets.token_urlsafe(24)
    sequence = generate_sequence(settings.LIVENESS_CHALLENGE_ACTIONS, settings.LIVENESS_CHALLENGE_STEPS)
    ttl = settings.LIVENESS_CHALLENGE_TTL_SECONDS
    record = {
        "student_id": student_id, "session_id": session_id, "sequence": sequence,
        "attempts_expire_at": _epoch(window_closes_at) + _ATTEMPTS_MARGIN_SECONDS,
    }
    try:
        state = _read_state(client, student_id, session_id)
        if state.attempts_left == 0:
            raise AttemptsExhausted
        client.set(_KEY.format(challenge_id), json.dumps(record), ex=ttl)
    except redis.RedisError as exc:
        logger.warning("Redis unavailable; could not issue liveness challenge")
        raise ChallengeUnavailable from exc
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=ttl)
    return IssuedChallenge(
        challenge_id=challenge_id, sequence=sequence, expires_at=expires_at, attempts_left=state.attempts_left
    )


class ConsumeStatus(str, Enum):
    OK = "ok"
    INVALID = "invalid"  # unknown or expired
    REUSED = "reused"  # already consumed once
    OTHER_STUDENT = "other_student"  # issued to someone else
    WRONG_SESSION = "wrong_session"  # this student's, but for another session
    UNAVAILABLE = "unavailable"  # Redis down
    EXHAUSTED = "exhausted"  # verify only: no attempts left


class Outcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"  # steps not performed; retryable
    SPOOF = "spoof"  # Module 3 says it isn't a live person; ends the attempts
    UNVERIFIED = "unverified"  # Module 3 gave no usable answer; no attempt used


@dataclass
class ConsumeResult:
    status: ConsumeStatus
    sequence: Optional[List[str]] = None
    # Set when the challenge went through verify first. None: never
    # verified, or Module 3 hadn't answered yet (treated the same).
    outcome: Optional[Outcome] = None
    frames_hash: Optional[str] = None
    liveness_score: Optional[float] = None


def _missing_status(client: redis.Redis, challenge_id: str) -> ConsumeStatus:
    reused = bool(client.exists(_USED_KEY.format(challenge_id)))
    return ConsumeStatus.REUSED if reused else ConsumeStatus.INVALID


def consume(challenge_id: str, student_id: str, session_id: str) -> ConsumeResult:
    """Atomically takes the challenge (or its verify result), so it can never
    be used twice - even when the check-in that names it then fails, or
    names the wrong session."""
    client = _get_client()
    try:
        raw = client.getdel(_KEY.format(challenge_id))
        if raw is None:
            raw = client.getdel(_RESULT_KEY.format(challenge_id))
            if raw is None:
                return ConsumeResult(_missing_status(client, challenge_id))
        client.set(_USED_KEY.format(challenge_id), "1", ex=_USED_MARKER_SECONDS)
    except redis.RedisError:
        logger.warning("Redis unavailable; could not verify liveness challenge")
        return ConsumeResult(ConsumeStatus.UNAVAILABLE)

    record = json.loads(raw)
    if record.get("student_id") != student_id:
        return ConsumeResult(ConsumeStatus.OTHER_STUDENT)
    if record.get("session_id") != session_id:
        return ConsumeResult(ConsumeStatus.WRONG_SESSION)
    outcome = record.get("outcome")
    return ConsumeResult(
        ConsumeStatus.OK,
        sequence=list(record.get("sequence") or []),
        outcome=Outcome(outcome) if outcome else None,
        frames_hash=record.get("frames_hash"),
        liveness_score=record.get("liveness_score"),
    )


@dataclass
class VerifyStart:
    status: ConsumeStatus
    session_id: Optional[str] = None
    sequence: Optional[List[str]] = None
    attempt: int = 0  # 1-based number of this attempt
    record: Optional[dict] = None


def begin_verify(challenge_id: str, student_id: str) -> VerifyStart:
    """Claims the challenge for one verify and counts the attempt.

    RENAME is atomic, so of two verifies of the same challenge only one gets
    it. The attempt is counted with HINCRBY before Module 3 is called, so
    parallel verifies of different challenges can't exceed the cap either."""
    settings = get_settings()
    client = _get_client()
    result_key = _RESULT_KEY.format(challenge_id)
    try:
        try:
            client.rename(_KEY.format(challenge_id), result_key)
        except redis.ResponseError:  # no such key
            return VerifyStart(_missing_status(client, challenge_id))
        client.set(_USED_KEY.format(challenge_id), "1", ex=_USED_MARKER_SECONDS)
        raw = client.get(result_key)
        if raw is None:  # expired in between
            return VerifyStart(ConsumeStatus.INVALID)
        record = json.loads(raw)
        if record.get("student_id") != student_id:
            client.delete(result_key)
            return VerifyStart(ConsumeStatus.OTHER_STUDENT)
        session_id = record["session_id"]
        attempts_key = _ATTEMPTS_KEY.format(student_id, session_id)
        if client.hget(attempts_key, "spoof") == "1":
            client.delete(result_key)
            return VerifyStart(ConsumeStatus.EXHAUSTED, session_id=session_id)
        used = client.hincrby(attempts_key, "used", 1)
        client.expireat(attempts_key, record["attempts_expire_at"])
        if used > settings.LIVENESS_MAX_ATTEMPTS:
            client.hincrby(attempts_key, "used", -1)
            client.delete(result_key)
            return VerifyStart(ConsumeStatus.EXHAUSTED, session_id=session_id)
    except redis.RedisError:
        logger.warning("Redis unavailable; could not start liveness verify")
        return VerifyStart(ConsumeStatus.UNAVAILABLE)
    return VerifyStart(
        ConsumeStatus.OK, session_id=session_id, sequence=list(record.get("sequence") or []),
        attempt=used, record=record,
    )


def finish_verify(
    challenge_id: str, student_id: str, start: VerifyStart, outcome: Outcome,
    frames_hash: str, liveness_score: float,
) -> Optional[int]:
    """Records the outcome for the check-in and updates the attempts.
    Returns attempts left, or None if Redis failed here."""
    settings = get_settings()
    client = _get_client()
    attempts_key = _ATTEMPTS_KEY.format(student_id, start.session_id)
    record = dict(start.record or {})
    record.update({"outcome": outcome.value, "frames_hash": frames_hash, "liveness_score": liveness_score})
    try:
        pipe = client.pipeline()
        if outcome == Outcome.FAILED:
            pipe.hincrby(attempts_key, "failed", 1)
        elif outcome == Outcome.SPOOF:
            pipe.hset(attempts_key, "spoof", "1")
        elif outcome == Outcome.UNVERIFIED:
            pipe.hincrby(attempts_key, "used", -1)
        pipe.expireat(attempts_key, record["attempts_expire_at"])
        # A fresh TTL: the student needs time to submit the check-in.
        pipe.set(_RESULT_KEY.format(challenge_id), json.dumps(record), ex=settings.LIVENESS_CHALLENGE_TTL_SECONDS)
        pipe.execute()
        return _read_state(client, student_id, start.session_id).attempts_left
    except redis.RedisError:
        logger.warning("Redis unavailable; could not record liveness verify outcome")
        return None
