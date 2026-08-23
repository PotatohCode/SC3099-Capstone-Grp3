from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.models._helpers import gen_uuid
from app.db.models.enums import SessionStatus


class ClassSession(Base):
    """
    A class meeting where students check in.

    Named `ClassSession` (table `sessions`) to avoid colliding with
    SQLAlchemy's own `Session` class in code that imports both.
    """
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=False, index=True)
    instructor_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    name = Column(String(255), nullable=False)
    session_type = Column(String(50), nullable=False, default="lecture")  # lecture|tutorial|lab|exam
    description = Column(Text, nullable=True)

    scheduled_start = Column(DateTime, nullable=False)
    scheduled_end = Column(DateTime, nullable=False)
    checkin_opens_at = Column(DateTime, nullable=False, index=True)
    checkin_closes_at = Column(DateTime, nullable=False, index=True)

    status = Column(String(20), nullable=False, default=SessionStatus.SCHEDULED.value, index=True)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)

    # Overrides course defaults when set
    venue_latitude = Column(Float, nullable=True)
    venue_longitude = Column(Float, nullable=True)
    venue_name = Column(String(255), nullable=True)
    geofence_radius_meters = Column(Float, nullable=True)

    require_liveness_check = Column(Boolean, nullable=False, default=True)
    require_face_match = Column(Boolean, nullable=False, default=False)
    risk_threshold = Column(Float, nullable=True)

    qr_code_secret = Column(String(64), nullable=True)
    qr_code_expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    course = relationship("Course", back_populates="sessions")
    instructor = relationship("User", back_populates="taught_sessions", foreign_keys=[instructor_id])
    checkins = relationship("CheckIn", back_populates="session")
