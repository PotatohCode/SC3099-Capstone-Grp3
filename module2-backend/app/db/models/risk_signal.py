from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.models._helpers import gen_uuid


class RiskSignal(Base):
    """Individual risk indicator contributing to a check-in's risk_score."""
    __tablename__ = "risk_signals"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    checkin_id = Column(String(36), ForeignKey("checkins.id"), nullable=False, index=True)

    signal_type = Column(String(50), nullable=False, index=True)  # see enums.RiskSignalType
    severity = Column(String(20), nullable=False, index=True)  # see enums.RiskSeverity
    confidence = Column(Float, nullable=False, default=1.0)
    details = Column(Text, nullable=True)  # JSON metadata
    weight = Column(Float, nullable=False, default=0.1)
    detected_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)

    # Relationships
    checkin = relationship("CheckIn", back_populates="risk_signals")
