from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


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


class CheckinResponse(BaseModel):
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


class CheckinListItem(BaseModel):
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


class MyCheckinItem(BaseModel):
    """GET /checkins/my-checkins item."""

    id: str
    session_id: str
    session_name: str
    course_code: str
    status: str
    checked_in_at: datetime
    risk_score: float


class SessionCheckinItem(BaseModel):
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


class FlaggedCheckinItem(BaseModel):
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
