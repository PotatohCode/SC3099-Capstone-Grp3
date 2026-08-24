from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.models._helpers import gen_uuid


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, index=True)  # UserRole enum value

    is_active = Column(Boolean, nullable=False, default=True, index=True)
    camera_consent = Column(Boolean, nullable=False, default=False)
    geolocation_consent = Column(Boolean, nullable=False, default=False)

    # Privacy: SimHash (256-hyperplane locality-sensitive hash, 64 hex
    # chars) only, NEVER a raw embedding/image. Team decision: SimHash, not
    # the SHA-256 shown in API-SPECIFICATION.md/SECURITY-REQUIREMENTS.md -
    # see IMPLEMENTATION-PLAN.md's "Team decisions" section. Backend stores
    # this as an opaque string regardless; Module 3 computes it.
    face_embedding_hash = Column(String(64), nullable=True)
    face_enrolled = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    last_login_at = Column(DateTime, nullable=True)
    scheduled_deletion_at = Column(DateTime, nullable=True)

    # Relationships
    enrollments = relationship("Enrollment", back_populates="student", foreign_keys="Enrollment.student_id")
    devices = relationship("Device", back_populates="user")
    checkins = relationship("CheckIn", back_populates="student", foreign_keys="CheckIn.student_id")
    taught_sessions = relationship("ClassSession", back_populates="instructor", foreign_keys="ClassSession.instructor_id")
    taught_courses = relationship("Course", back_populates="instructor", foreign_keys="Course.instructor_id")
