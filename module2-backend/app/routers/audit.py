"""
Audit log retrieval (Phase 7a). audit_logs has been populated since Phase 2
(auth.py's log_event calls) - this is purely "expose what's already
written" with filters. See KNOWN-ISSUES.md before touching this file:
audit_logs is insert-only, no code anywhere should ever UPDATE a row.

GET /audit/summary isn't in API-SPECIFICATION.md's written text - it only
exists in tests/public/test_observability.py::test_audit_summary. Test
wins per IMPLEMENTATION-PLAN.md's own rule; see schemas/audit.py's comment
for exactly what's tested vs. what's added for real usefulness.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_role
from app.db.models.audit_log import AuditLog
from app.db.models.user import User
from app.schemas.audit import AuditLogItem, AuditSummaryResponse
from app.schemas.common import Page

router = APIRouter(prefix="/audit", tags=["audit"])


def _parse_details(raw: Optional[str]):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/summary", response_model=AuditSummaryResponse)
def audit_summary(
    days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    since = _now() - timedelta(days=days)
    base = db.query(AuditLog).filter(AuditLog.timestamp >= since)
    total = base.count()
    success_count = base.filter(AuditLog.success.is_(True)).count()
    failed_count = base.filter(AuditLog.success.is_(False)).count()

    by_action = dict(
        db.query(AuditLog.action, func.count(AuditLog.id))
        .filter(AuditLog.timestamp >= since)
        .group_by(AuditLog.action)
        .all()
    )

    return AuditSummaryResponse(
        period_days=days, total_logs=total, success_count=success_count,
        failed_count=failed_count, by_action=by_action,
    )


@router.get("/", response_model=Page[AuditLogItem])
def list_audit_logs(
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    success: Optional[bool] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    # No `user` relationship on AuditLog (deliberately - it's a log table,
    # not a domain entity) so join explicitly rather than via ORM relationship.
    query = db.query(AuditLog, User.email).outerjoin(User, AuditLog.user_id == User.id)

    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.filter(AuditLog.resource_id == resource_id)
    if success is not None:
        query = query.filter(AuditLog.success == success)
    if start_date:
        query = query.filter(AuditLog.timestamp >= start_date)
    if end_date:
        query = query.filter(AuditLog.timestamp <= end_date)

    total = query.count()
    rows = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
    items = [
        AuditLogItem(
            id=log.id, user_id=log.user_id, user_email=user_email, action=log.action,
            resource_type=log.resource_type, resource_id=log.resource_id, ip_address=log.ip_address,
            user_agent=log.user_agent, device_id=log.device_id, details=_parse_details(log.details),
            success=log.success, timestamp=log.timestamp,
        )
        for log, user_email in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)
