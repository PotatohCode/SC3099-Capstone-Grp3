from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.models._helpers import gen_uuid


class AuditLog(Base):
    """
    Immutable audit trail.

    IMPORTANT: no `updated_at` column, and no code anywhere should ever
    UPDATE a row here — insert-only. See enums.AuditAction for the tracked
    action types.
    """
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(50), nullable=False, index=True)  # see enums.AuditAction
    resource_type = Column(String(50), nullable=True, index=True)  # user|checkin|session|course|...
    resource_id = Column(String(36), nullable=True, index=True)
    ip_address = Column(String(45), nullable=True, index=True)  # IPv4/IPv6
    user_agent = Column(String(500), nullable=True)
    device_id = Column(String(36), nullable=True)
    details = Column(Text, nullable=True)  # JSON details
    success = Column(Boolean, nullable=False, default=True)
    timestamp = Column(DateTime, nullable=False, server_default=func.now(), index=True)
