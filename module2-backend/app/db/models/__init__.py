"""
Import every model here so `Base.metadata` is fully populated for Alembic
autogenerate and for `Base.metadata.create_all()` in tests/local dev.
"""
from app.db.models.audit_log import AuditLog
from app.db.models.checkin import CheckIn
from app.db.models.course import Course
from app.db.models.device import Device
from app.db.models.enrollment import Enrollment
from app.db.models.risk_signal import RiskSignal
from app.db.models.session import ClassSession
from app.db.models.user import User

__all__ = [
    "AuditLog",
    "CheckIn",
    "Course",
    "Device",
    "Enrollment",
    "RiskSignal",
    "ClassSession",
    "User",
]
