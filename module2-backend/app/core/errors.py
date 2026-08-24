"""
Centralized error codes and the APIError exception.

Team decision (see IMPLEMENTATION-PLAN.md's "Team decisions that deviate
from the written docs"): every non-422 error body gets a machine-readable
`code` field on top of API-SPECIFICATION.md's bare `{"detail": "..."}`:

    { "detail": "Human-readable message", "code": "ERROR_CODE" }

422 validation errors are untouched — FastAPI's default
`{"detail": [...]}` field-error list stays as-is, no `code` added.

Usage: raise `APIError(status_code, detail, code)` from routers/deps
instead of a plain `HTTPException`. A plain `HTTPException` still works
(see the fallback handler in main.py) but gets a generic status-derived
code instead of a precise one — prefer APIError going forward.
"""
from typing import Optional

from fastapi import HTTPException


class ErrorCode:
    # 400
    BAD_REQUEST = "BAD_REQUEST"
    EMAIL_ALREADY_REGISTERED = "EMAIL_ALREADY_REGISTERED"
    WEAK_PASSWORD = "WEAK_PASSWORD"
    ALREADY_ENROLLED = "ALREADY_ENROLLED"
    ALREADY_CHECKED_IN = "ALREADY_CHECKED_IN"
    SESSION_NOT_ACTIVE = "SESSION_NOT_ACTIVE"
    COURSE_CODE_TAKEN = "COURSE_CODE_TAKEN"
    INVALID_SCHEDULE = "INVALID_SCHEDULE"
    SESSION_NOT_DELETABLE = "SESSION_NOT_DELETABLE"
    DEVICE_FINGERPRINT_TAKEN = "DEVICE_FINGERPRINT_TAKEN"
    SESSION_WINDOW_CLOSED = "SESSION_WINDOW_CLOSED"
    ALREADY_APPEALED = "ALREADY_APPEALED"
    APPEAL_NOT_ALLOWED = "APPEAL_NOT_ALLOWED"
    APPEAL_WINDOW_EXPIRED = "APPEAL_WINDOW_EXPIRED"
    REVIEW_NOT_ALLOWED = "REVIEW_NOT_ALLOWED"
    CAMERA_CONSENT_REQUIRED = "CAMERA_CONSENT_REQUIRED"
    NO_FACE_DETECTED = "NO_FACE_DETECTED"
    NOT_ENROLLED = "NOT_ENROLLED"
    # 401
    INVALID_TOKEN = "INVALID_TOKEN"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INVALID_REFRESH_TOKEN = "INVALID_REFRESH_TOKEN"
    # 403
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    # 404
    NOT_FOUND = "NOT_FOUND"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    STUDENT_NOT_FOUND = "STUDENT_NOT_FOUND"
    COURSE_NOT_FOUND = "COURSE_NOT_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    ENROLLMENT_NOT_FOUND = "ENROLLMENT_NOT_FOUND"
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    CHECKIN_NOT_FOUND = "CHECKIN_NOT_FOUND"
    # 429
    RATE_LIMITED = "RATE_LIMITED"
    # 500
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # 503
    FACE_SERVICE_UNAVAILABLE = "FACE_SERVICE_UNAVAILABLE"


# Fallback for any plain `HTTPException(...)` call site not yet migrated to
# APIError, so it still emits *a* code instead of a missing field.
DEFAULT_CODE_BY_STATUS: dict[int, str] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.INVALID_TOKEN,
    403: ErrorCode.INSUFFICIENT_PERMISSIONS,
    404: ErrorCode.NOT_FOUND,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL_ERROR,
    503: ErrorCode.FACE_SERVICE_UNAVAILABLE,
}


class APIError(HTTPException):
    """HTTPException that carries a machine-readable `code` alongside `detail`."""

    def __init__(self, status_code: int, detail: str, code: str, headers: Optional[dict] = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
