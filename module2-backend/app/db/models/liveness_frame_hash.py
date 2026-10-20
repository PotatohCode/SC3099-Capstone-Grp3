from sqlalchemy import Column, ForeignKey, Index, String

from app.db.base import Base
from app.db.models._helpers import gen_uuid


class LivenessFrameHash(Base):
    """SHA-256 of each image a check-in submitted (the single photo, or every
    frame of a burst) - never the image itself. Replay detection looks up
    the student's earlier hashes here, so reusing any one frame of an old
    burst is caught, not only the identical burst. Rows are deleted by the
    retention sweep along with the check-in's other image-derived data."""

    __tablename__ = "liveness_frame_hashes"
    __table_args__ = (Index("ix_liveness_frame_hashes_student_hash", "student_id", "frame_hash"),)

    id = Column(String(36), primary_key=True, default=gen_uuid)
    checkin_id = Column(String(36), ForeignKey("checkins.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    frame_hash = Column(String(64), nullable=False)
