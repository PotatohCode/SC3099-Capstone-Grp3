from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class DayCount(BaseModel):
    date: str
    count: int


class DayRate(BaseModel):
    date: str
    rate: float


class OverviewTrends(BaseModel):
    checkins_by_day: List[DayCount] = []
    attendance_rate_by_day: List[DayRate] = []


class StatsOverviewResponse(BaseModel):
    """GET /stats/overview. Field names are a superset of both
    API-SPECIFICATION.md's example and tests/public/test_observability.py's
    actual assertions, which use different names for several of the same
    values (test wins - see KNOWN-ISSUES.md) - both are populated so the
    response satisfies the test exactly while staying compatible with
    anything built against the written spec's names."""

    # Test-required names
    total_sessions: int
    active_sessions: int
    total_courses: int
    total_students: int
    today_checkins: int
    flagged_pending: int
    approval_rate: float
    # Doc names covering the same values, plus richer detail
    total_checkins_today: int
    total_checkins_week: int
    average_attendance_rate: float
    flagged_pending_review: int
    average_risk_score: float
    high_risk_checkins_today: int
    trends: OverviewTrends


class ByStatusCounts(BaseModel):
    approved: int = 0
    flagged: int = 0
    rejected: int = 0
    pending: int = 0
    appealed: int = 0


class RiskDistribution(BaseModel):
    low: int = 0
    medium: int = 0
    high: int = 0


class TimelinePoint(BaseModel):
    minute: int
    count: int


class SessionStatsResponse(BaseModel):
    session_id: str
    session_name: str
    course_code: str
    scheduled_start: datetime
    status: str
    total_enrolled: int
    checked_in: int
    checked_in_count: int  # same value as checked_in - test uses this name, doc uses checked_in
    approved_count: int
    flagged_count: int
    attendance_rate: float
    by_status: ByStatusCounts
    average_risk_score: float
    average_distance_meters: Optional[float] = None
    average_checkin_time_minutes: Optional[float] = None
    risk_distribution: RiskDistribution
    checkin_timeline: List[TimelinePoint] = []


class CourseSessionSummary(BaseModel):
    session_id: str
    name: str
    date: str
    attendance_rate: float
    checked_in: int


class StudentAttendanceItem(BaseModel):
    student_id: str
    student_name: str
    sessions_attended: int
    attendance_rate: float
    average_risk_score: float


class LowAttendanceAlert(BaseModel):
    student_id: str
    student_name: str
    attendance_rate: float
    sessions_missed: int


class CourseStatsResponse(BaseModel):
    course_id: str
    course_code: str
    course_name: str
    total_sessions: int
    total_enrolled: int
    overall_attendance_rate: float
    average_attendance_rate: float  # same value - test uses this name, doc uses overall_attendance_rate
    flagged_checkins: int
    sessions: List[CourseSessionSummary] = []
    student_attendance: List[StudentAttendanceItem] = []
    low_attendance_alerts: List[LowAttendanceAlert] = []


class StudentCourseStats(BaseModel):
    course_id: str
    course_code: str
    attendance_rate: float
    sessions_attended: int
    total_sessions: int
    average_risk_score: float


class RecentCheckinItem(BaseModel):
    session_name: str
    course_code: str
    checked_in_at: datetime
    status: str


class StudentStatsResponse(BaseModel):
    student_id: str
    student_name: str
    student_email: str
    total_enrolled_courses: int
    total_sessions: int
    attended_sessions: int
    attendance_rate: float
    courses: List[StudentCourseStats] = []
    recent_sessions: List[RecentCheckinItem] = []  # test name
    recent_checkins: List[RecentCheckinItem] = []  # doc name, same content
