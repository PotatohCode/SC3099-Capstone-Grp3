from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ExportRecord(BaseModel):
    """One row - shared shape for both course and session export, matching
    API-SPECIFICATION.md's CSV column list for /export/attendance/{course_id}
    (session export's own section doesn't give different columns, so the
    same schema is reused for both)."""

    student_id: str
    student_name: str
    student_email: str
    session_date: str
    session_name: str
    status: str
    checked_in_at: Optional[datetime] = None
    risk_score: float


class SessionExportSummary(BaseModel):
    total_enrolled: int
    checked_in_count: int
    attendance_rate: float
    approved_count: int
    flagged_count: int
    average_risk_score: float


class SessionExportResponse(BaseModel):
    """GET /export/session/{id}?format=json. Not documented as an object
    shape anywhere in API-SPECIFICATION.md's Export section (just "returns
    a downloadable file") - built to match
    tests/public/test_observability.py::test_export_session_attendance_json
    exactly, which is the only test covering export at all."""

    session_id: str
    session_name: str
    summary: SessionExportSummary
    records: List[ExportRecord]
