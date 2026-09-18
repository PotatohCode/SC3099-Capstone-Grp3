from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.models._helpers import gen_uuid
from app.db.models.enums import CheckinStatus


class CheckIn(Base):
    __tablename__ = "checkins"
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_checkin_session_student"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=True)

    status = Column(String(20), nullable=False, default=CheckinStatus.PENDING.value, index=True)
    checked_in_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    verified_at = Column(DateTime, nullable=True)

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_accuracy_meters = Column(Float, nullable=True)
    distance_from_venue_meters = Column(Float, nullable=True)

    liveness_passed = Column(Boolean, nullable=True)
    liveness_score = Column(Float, nullable=True)
    liveness_challenge_type = Column(String(50), nullable=True)  # blink|head_turn|speak

    face_match_passed = Column(Boolean, nullable=True)
    face_match_score = Column(Float, nullable=True)
    face_embedding_hash = Column(String(64), nullable=True)  # SimHash, never raw - see users.face_embedding_hash

    risk_score = Column(Float, nullable=False, default=0.0, index=True)
    risk_factors = Column(Text, nullable=True)  # JSON array, serialized

    qr_code_verified = Column(Boolean, nullable=False, default=False)

    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)

    appeal_reason = Column(Text, nullable=True)
    appealed_at = Column(DateTime, nullable=True)

    scheduled_deletion_at = Column(DateTime, nullable=True)

    # Relationships
    session = relationship("ClassSession", back_populates="checkins")
    student = relationship("User", back_populates="checkins", foreign_keys=[student_id])
    device = relationship("Device", back_populates="checkins")
    reviewer = relationship("User", foreign_keys=[reviewed_by_id])
    risk_signals = relationship("RiskSignal", back_populates="checkin")
