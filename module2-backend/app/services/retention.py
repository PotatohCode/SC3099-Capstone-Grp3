"""
PII retention sweep (SECURITY-REQUIREMENTS.md's "Data Retention" table -
Phase 7e). Anonymizes rather than hard-deletes: `checkins`/`users` rows are
referenced by risk_signals/enrollments/devices/audit_logs/taught
courses+sessions, and audit_logs specifically must stay indefinite and
immutable, so a real DELETE would either cascade destructively through
half the schema or violate that immutability requirement (an audit row's
user_id would dangle or have to be nulled out either way). Anonymizing
scrubs the PII fields and keeps the row - and every FK to it - intact.

`scheduled_deletion_at` doubles as the "already processed" flag: sweeping
a row clears it back to NULL, so it's naturally excluded from the next
sweep without a separate `is_anonymized` column/migration.

Note the asymmetry between the two tables:
- `checkins.scheduled_deletion_at` is set automatically at check-in
  creation (see routers/checkins.py's create_checkin), so check-in
  retention is fully live end-to-end.
- `users.scheduled_deletion_at` is NOT set by anything yet - there is no
  account-deletion endpoint (self-service or admin) in this codebase.
  This sweep will correctly find zero eligible users until one exists.
  That's a deliberate scope boundary, not an oversight - see
  KNOWN-ISSUES.md.
"""
import uuid
from datetime import datetime, timezone
from typing import TypedDict

from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.db.models.checkin import CheckIn
from app.db.models.user import User


class RetentionSweepResult(TypedDict):
    users_anonymized: int
    checkins_anonymized: int


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def anonymize_user(user: User) -> None:
    """Scrub PII in place. The row and its id survive, so every FK
    (checkins.student_id, enrollments.student_id, devices.user_id,
    audit_logs.user_id, taught courses/sessions) stays valid."""
    # NOT the RFC 2606 "@example.com"/"@*.invalid"/"@*.local" reserved
    # names - FastAPI's response validation runs this back through
    # EmailStr (email-validator), which explicitly rejects those as
    # special-use and turns every read of an anonymized user into a 500.
    # Confirmed by testing the candidates directly against
    # email_validator.validate_email() before picking this one.
    user.email = f"deleted-{user.id}@saiv-deleted.internal"
    user.full_name = "Deleted User"
    user.hashed_password = get_password_hash(uuid.uuid4().hex)  # unusable, keeps column non-null/valid
    user.is_active = False
    user.camera_consent = False
    user.geolocation_consent = False
    user.face_embedding_hash = None
    user.face_enrolled = False
    user.scheduled_deletion_at = None  # mark processed


def anonymize_checkin(checkin: CheckIn) -> None:
    """Scrub location + biometric-derived fields; keep the row (and
    risk_signals' FK to it) intact - the audit trail itself (status,
    risk_score, timestamps) isn't PII, only the GPS coordinates and the
    face hash are."""
    checkin.latitude = None
    checkin.longitude = None
    checkin.location_accuracy_meters = None
    checkin.distance_from_venue_meters = None
    checkin.face_embedding_hash = None
    checkin.scheduled_deletion_at = None  # mark processed


def run_retention_sweep(db: Session) -> RetentionSweepResult:
    """Anonymizes every user/check-in whose `scheduled_deletion_at` has
    passed. Does NOT commit - matches services/audit.py's convention so
    the caller commits this atomically with its own audit log entry."""
    now = _now()

    due_users = (
        db.query(User).filter(User.scheduled_deletion_at.isnot(None), User.scheduled_deletion_at <= now).all()
    )
    for user in due_users:
        anonymize_user(user)

    due_checkins = (
        db.query(CheckIn).filter(CheckIn.scheduled_deletion_at.isnot(None), CheckIn.scheduled_deletion_at <= now).all()
    )
    for checkin in due_checkins:
        anonymize_checkin(checkin)

    return {"users_anonymized": len(due_users), "checkins_anonymized": len(due_checkins)}
