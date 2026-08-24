"""
Python-side enums for columns `DATABASE-SCHEMA.md` labels ENUM.

Deliberately mapped to plain String columns (see each model), not native
Postgres ENUM types — that avoids `ALTER TYPE ... ADD VALUE` migration pain
if a new status/action value is needed later, at the cost of enforcing the
allowed-values constraint at the Pydantic/service layer instead of the DB.
Given tests are black-box HTTP calls, not schema inspection, that trade-off
favors iteration speed.
"""
import enum


class UserRole(str, enum.Enum):
    STUDENT = "student"
    TA = "ta"
    INSTRUCTOR = "instructor"
    ADMIN = "admin"


class SessionStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class CheckinStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    FLAGGED = "flagged"
    REJECTED = "rejected"
    APPEALED = "appealed"


class RiskSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskSignalType(str, enum.Enum):
    # Geo
    GEO_OUT_OF_BOUNDS = "geo_out_of_bounds"
    IMPOSSIBLE_TRAVEL = "impossible_travel"
    GEO_ACCURACY_LOW = "geo_accuracy_low"
    # Network
    VPN_DETECTED = "vpn_detected"
    PROXY_DETECTED = "proxy_detected"
    TOR_DETECTED = "tor_detected"
    SUSPICIOUS_IP = "suspicious_ip"
    # Device
    DEVICE_UNKNOWN = "device_unknown"
    DEVICE_EMULATOR = "device_emulator"
    DEVICE_ROOTED = "device_rooted"
    ATTESTATION_FAILED = "attestation_failed"
    # Behavioral
    RAPID_SUCCESSION = "rapid_succession"
    UNUSUAL_TIME = "unusual_time"
    PATTERN_ANOMALY = "pattern_anomaly"
    # Liveness
    LIVENESS_FAILED = "liveness_failed"
    LIVENESS_LOW_CONFIDENCE = "liveness_low_confidence"
    DEEPFAKE_SUSPECTED = "deepfake_suspected"
    REPLAY_SUSPECTED = "replay_suspected"
    # Face
    FACE_MATCH_FAILED = "face_match_failed"
    FACE_MATCH_LOW_CONFIDENCE = "face_match_low_confidence"


class AuditAction(str, enum.Enum):
    # From API-SPECIFICATION.md's 18 tracked actions
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    CHECKIN_ATTEMPTED = "checkin_attempted"
    CHECKIN_APPROVED = "checkin_approved"
    CHECKIN_FLAGGED = "checkin_flagged"
    CHECKIN_REJECTED = "checkin_rejected"
    CHECKIN_APPEALED = "checkin_appealed"
    CHECKIN_REVIEWED = "checkin_reviewed"
    SESSION_CREATED = "session_created"
    SESSION_UPDATED = "session_updated"
    SESSION_DELETED = "session_deleted"
    ENROLLMENT_ADDED = "enrollment_added"
    ENROLLMENT_REMOVED = "enrollment_removed"
    DEVICE_REGISTERED = "device_registered"
    FACE_ENROLLED = "face_enrolled"
    # Additional events SECURITY-REQUIREMENTS.md's "Required Events" table
    # requires that aren't in the API-SPEC's 18-item list
    DATA_EXPORTED = "data_exported"
    SECURITY_VIOLATION = "security_violation"
    # Course CRUD isn't in the API-SPEC's 18-item list either (an apparent
    # oversight - session_created/updated/deleted are, courses aren't) but
    # course changes are just as security-relevant, so tracked the same way.
    COURSE_CREATED = "course_created"
    COURSE_UPDATED = "course_updated"
    COURSE_DELETED = "course_deleted"
