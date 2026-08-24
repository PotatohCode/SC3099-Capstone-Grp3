"""
HTTP client for Module 3 (Face Recognition Service) - centralizes the
timeout/degrade pattern IMPLEMENTATION-PLAN.md's Phase 6 resilience note
requires: 5s timeout, no auth (internal call), and every failure mode
(timeout, connection error, non-2xx, malformed JSON) returns None rather
than raising - callers degrade gracefully instead of failing the check-in.

As of this writing module3-face-recognition is an unimplemented stub (every
endpoint 501s - see KNOWN-ISSUES.md), so in practice every call here
currently returns None. That's the exact scenario this pattern exists for.

Circuit breaker: a failure (of any kind, including a DNS lookup failure
for an unresolvable host - measured at ~2.5s in this environment, and
notably NOT something httpx's own connect-timeout can shorten, since the
delay is inside the OS's blocking getaddrinfo() call, not httpx's request
loop) opens the breaker for that path for COOLDOWN_SECONDS. Calls made
while open skip the network entirely and return None immediately. Without
this, every check-in in a burst (e.g. the test suite) would separately
pay the full failure cost, and test_performance.py's
test_checkin_endpoint_latency (< 2s) could never pass while Module 3 is
unreachable. This is also just good production behavior, not only a test
accommodation - don't keep hammering a dependency that's already down.
"""
import logging
import time
from typing import Any, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger("saiv.face_client")

TIMEOUT_SECONDS = 5.0
COOLDOWN_SECONDS = 30.0

_circuit_open_until: dict[str, float] = {}


def _post(path: str, payload: dict) -> Optional[dict[str, Any]]:
    now = time.monotonic()
    if _circuit_open_until.get(path, 0.0) > now:
        return None

    settings = get_settings()
    url = f"{settings.FACE_SERVICE_URL}{path}"
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            _circuit_open_until.pop(path, None)  # a success clears any prior cooldown
            return response.json()
    except httpx.TimeoutException:
        logger.warning("Face service timeout calling %s", path)
    except httpx.HTTPError as exc:
        logger.warning("Face service error calling %s: %s", path, exc)
    except ValueError:
        # response.json() failed to parse - treat as unavailable, same as
        # any other integration failure.
        logger.warning("Face service returned unparseable JSON from %s", path)

    _circuit_open_until[path] = now + COOLDOWN_SECONDS
    return None


def enroll_face(user_id: str, image_base64: str, camera_consent: bool) -> Optional[dict[str, Any]]:
    """POST /face/enroll. None on any failure - caller must reject the
    enrollment request (unlike check-in, there's no sensible "enroll
    anyway" fallback)."""
    return _post("/face/enroll", {"user_id": user_id, "image": image_base64, "camera_consent": camera_consent})


def verify_face(image_base64: str, reference_template_hash: str) -> Optional[dict[str, Any]]:
    """POST /face/verify. None on any failure - caller degrades to
    face_match_passed=None, face_match_score=0.0."""
    return _post("/face/verify", {"image": image_base64, "reference_template_hash": reference_template_hash})


def check_liveness(image_base64: str, challenge_type: str = "passive") -> Optional[dict[str, Any]]:
    """POST /liveness/check. None on any failure - caller degrades to
    liveness_passed=None, liveness_score=0.0 (per INTEGRATION-GUIDE.md's
    sample - None, not False, so an unattempted/unreachable check never
    triggers the liveness-failed hard-override on its own)."""
    return _post("/liveness/check", {"challenge_response": image_base64, "challenge_type": challenge_type})


def assess_risk(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """POST /risk/assess. None on any failure - caller falls back to
    services/risk_scoring.py's local approximation formula."""
    return _post("/risk/assess", payload)
