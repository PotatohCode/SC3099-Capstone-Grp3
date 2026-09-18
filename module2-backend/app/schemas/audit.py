from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class AuditLogItem(BaseModel):
    id: str
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    success: bool
    timestamp: datetime


class AuditSummaryResponse(BaseModel):
    """GET /audit/summary - not in API-SPECIFICATION.md's written text, only
    in tests/public/test_observability.py::test_audit_summary (asserts
    period_days + total_logs). The extra fields go beyond what's tested,
    matching the endpoint's stated purpose (a real summary, not just the
    two required keys)."""

    period_days: int
    total_logs: int
    success_count: int
    failed_count: int
    by_action: Dict[str, int]
