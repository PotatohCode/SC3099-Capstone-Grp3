"""
Audit log writes. See db/models/audit_log.py: insert-only, no updates ever.

Deliberately does NOT call db.commit() - that's the caller's job, so the
audit row commits atomically together with whatever action it's recording
(e.g. a failed login's audit entry should still be recorded even though
there's no user row being written, and a successful registration's audit
entry should never exist without the user row actually having been created).
"""
import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.models.audit_log import AuditLog


def log_event(
    db: Session,
    action: str,
    user_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    success: bool = True,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details=json.dumps(details) if details is not None else None,
            success=success,
        )
    )
