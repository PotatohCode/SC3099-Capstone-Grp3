from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.models._helpers import gen_uuid


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", name="uq_enrollment_student_course"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(String(36), ForeignKey("courses.id"), nullable=False, index=True)

    is_active = Column(Boolean, nullable=False, default=True)
    enrolled_at = Column(DateTime, nullable=False, server_default=func.now())
    dropped_at = Column(DateTime, nullable=True)

    # Relationships
    student = relationship("User", back_populates="enrollments", foreign_keys=[student_id])
    course = relationship("Course", back_populates="enrollments")
