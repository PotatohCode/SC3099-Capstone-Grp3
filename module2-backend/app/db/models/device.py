from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.models._helpers import gen_uuid


class Device(Base):
    __tablename__ = "devices"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    device_fingerprint = Column(String(64), unique=True, nullable=False, index=True)
    device_name = Column(String(255), nullable=True)
    platform = Column(String(50), nullable=True)  # ios|android|web|desktop
    browser = Column(String(100), nullable=True)
    os_version = Column(String(50), nullable=True)
    app_version = Column(String(50), nullable=True)

    # DEVIATION from DATABASE-SCHEMA.md (which marks public_key NOT NULL):
    # tests/conftest.py's test_device fixture registers devices without a
    # public_key at all, so it must be optional to match the tested contract.
    public_key = Column(Text, nullable=True)
    public_key_created_at = Column(DateTime, nullable=True)
    public_key_expires_at = Column(DateTime, nullable=True)

    attestation_passed = Column(Boolean, nullable=False, default=False)
    last_attestation_at = Column(DateTime, nullable=True)
    attestation_token = Column(Text, nullable=True)

    is_trusted = Column(Boolean, nullable=False, default=False, index=True)
    trust_score = Column(String(20), nullable=False, default="low")  # low|medium|high
    is_emulator = Column(Boolean, nullable=False, default=False)
    is_rooted_jailbroken = Column(Boolean, nullable=False, default=False)

    first_seen_at = Column(DateTime, nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime, nullable=False, server_default=func.now())
    total_checkins = Column(Integer, nullable=False, default=0)

    is_active = Column(Boolean, nullable=False, default=True, index=True)
    revoked_at = Column(DateTime, nullable=True)
    revocation_reason = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="devices")
    checkins = relationship("CheckIn", back_populates="device")
