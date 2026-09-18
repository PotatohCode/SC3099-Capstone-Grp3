from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.models._helpers import gen_uuid


class Course(Base):
    __tablename__ = "courses"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    semester = Column(String(20), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    # DEVIATION from DATABASE-SCHEMA.md: that doc's courses table has no
    # instructor_id column, but API-SPECIFICATION.md's course request/response
    # bodies do ("instructor_id", "instructor_name"), and several endpoints'
    # access rules ("admin or course instructor") need a direct owner rather
    # than deriving it transitively through sessions. Kept nullable since a
    # course can exist before an instructor is assigned.
    instructor_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)

    venue_latitude = Column(Float, nullable=True)
    venue_longitude = Column(Float, nullable=True)
    venue_name = Column(String(255), nullable=True)
    geofence_radius_meters = Column(Float, nullable=False, default=100.0)

    require_face_recognition = Column(Boolean, nullable=False, default=False)
    require_device_binding = Column(Boolean, nullable=False, default=True)
    risk_threshold = Column(Float, nullable=False, default=0.5)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    instructor = relationship("User", back_populates="taught_courses", foreign_keys=[instructor_id])
    sessions = relationship("ClassSession", back_populates="course")
    enrollments = relationship("Enrollment", back_populates="course")
