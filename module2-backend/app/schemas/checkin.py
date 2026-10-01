from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, computed_field, Field

from app.services.risk_scoring import risk_level as _risk_level


class _RiskLevelMixin(BaseModel):
    """Adds `risk_level` (LOW/MEDIUM/HIGH/CRITICAL, SECURITY-REQUIREMENTS
    bands) derived from risk_score with the same function the backend uses
    to decide outcomes, so the two can never disagree."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def risk_level(self) -> str:
        return _risk_level(self.risk_score)


class CheckinCreate(BaseModel):
    session_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location_accuracy_meters: Optional[float] = Field(default=None, ge=0)
    device_fingerprint: str = Field(min_length=1, max_length=64)
    liveness_challenge_response: Optional[str] = None  # base64 image, optional
    qr_code: Optional[str] = None


class RiskFactorItem(BaseModel):
    type: str
    weight: float


class CheckinResponse(_RiskLevelMixin):
    """POST /checkins/ (201) and GET /checkins/{id} - full detail."""

    id: str
    session_id: str
    student_id: str
    device_id: Optional[str] = None
    status: str
    checked_in_at: datetime
    verified_at: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_accuracy_meters: Optional[float] = None
    distance_from_venue_meters: Optional[float] = None
    liveness_passed: Optional[bool] = None
    liveness_score: Optional[float] = None
    face_match_passed: Optional[bool] = None
    face_match_score: Optional[float] = None
    face_embedding_hash: Optional[str] = None
    risk_score: float
    risk_factors: List[RiskFactorItem] = []
    qr_code_verified: bool = False
    reviewed_by_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    appeal_reason: Optional[str] = None
    appealed_at: Optional[datetime] = None


class CheckinListItem(_RiskLevelMixin):
    """GET /checkins/ paginated item."""

    id: str
    session_id: str
    session_name: str
    student_id: str
    student_name: str
    student_email: str
    status: str
    checked_in_at: datetime
    distance_from_venue_meters: Optional[float] = None
    risk_score: float
    liveness_passed: Optional[bool] = None


class MyCheckinItem(_RiskLevelMixin):
    """GET /checkins/my-checkins item."""

    id: str
    session_id: str
    session_name: str
    course_code: str
    status: str
    checked_in_at: datetime
    risk_score: float


class SessionCheckinItem(_RiskLevelMixin):
    """GET /checkins/session/{id} item."""

    id: str
    student_id: str
    student_name: str
    student_email: str
    status: str
    checked_in_at: datetime
    distance_from_venue_meters: Optional[float] = None
    risk_score: float
    risk_factors: List[RiskFactorItem] = []
    liveness_passed: Optional[bool] = None
    device_trusted: Optional[bool] = None


class FlaggedCheckinRiskFactor(BaseModel):
    type: str
    severity: str
    weight: float


class FlaggedCheckinItem(_RiskLevelMixin):
    """GET /checkins/flagged item."""

    id: str
    session_id: str
    session_name: str
    student_id: str
    student_name: str
    status: str
    checked_in_at: datetime
    risk_score: float
    risk_factors: List[FlaggedCheckinRiskFactor] = []
    appeal_reason: Optional[str] = None
    appealed_at: Optional[datetime] = None


class CheckinAppealRequest(BaseModel):
    appeal_reason: str = Field(min_length=1, max_length=2000)


class CheckinAppealResponse(BaseModel):
    id: str
    status: str
    appeal_reason: Optional[str] = None
    appealed_at: Optional[datetime] = None


class CheckinReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]
    review_notes: Optional[str] = Field(default=None, max_length=2000)


class CheckinReviewResponse(BaseModel):
    id: str
    status: str
    reviewed_by_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
