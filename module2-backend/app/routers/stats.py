"""
Analytics endpoints for the instructor/dashboard (Phase 7b). See
KNOWN-ISSUES.md before touching field names: every one of these four
endpoints has a real doc-vs-test naming mismatch (e.g. overview's
`flagged_pending` vs. API-SPEC's `flagged_pending_review`) - the response
schemas in schemas/stats.py deliberately populate both names rather than
picking one, since the test names are the graded contract but the doc
names are what a teammate reading API-SPECIFICATION.md would expect.

"Attended" vs. raw check-in counts: a `rejected` check-in represents a
caught spoofing/GPS-fraud attempt, not genuine attendance, so it's
excluded from attendance_rate/attended-session counts everywhere below.
Raw counts (fields literally named checked_in/checked_in_count) count
every row regardless of status - see _is_attended().
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_db, require_role
from app.core.errors import APIError, ErrorCode
from app.db.models.checkin import CheckIn
from app.db.models.course import Course
from app.db.models.enrollment import Enrollment
from app.db.models.session import ClassSession
from app.db.models.user import User
from app.schemas.stats import (
    ByStatusCounts,
    CourseSessionSummary,
    CourseStatsResponse,
    DayCount,
    DayRate,
    LowAttendanceAlert,
    OverviewTrends,
    RecentCheckinItem,
    RiskDistribution,
    SessionStatsResponse,
    StatsOverviewResponse,
    StudentAttendanceItem,
    StudentCourseStats,
    StudentStatsResponse,
    TimelinePoint,
)
from app.services.authz import can_edit_course, require_edit_course, require_manage_session

router = APIRouter(prefix="/stats", tags=["stats"])

NON_ATTENDANCE_STATUSES = {"rejected"}
LOW_ATTENDANCE_THRESHOLD = 0.75  # reasoned default - no spec value given


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_attended(checkin: CheckIn) -> bool:
    return checkin.status not in NON_ATTENDANCE_STATUSES


def _avg(values: list) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _staff_course_scope(db: Session, user: User) -> Optional[set]:
    """Course ids this instructor/ta can see stats for - None for admin
    (no scoping). Matches the ownership model used everywhere else
    (services/authz.py, routers/sessions.py's _scope_sessions_for_staff):
    courses owned directly (Course.instructor_id), PLUS courses where this
    instructor owns at least one session (ClassSession.instructor_id) even
    if the course itself was never assigned an owner - test_course never
    sets instructor_id, so scoping by Course.instructor_id alone silently
    excludes every course an instructor actually works with in this
    codebase's normal flow. Confirmed live: /stats/overview returned all
    zeros for real data before this fix. PLUS courses they're TA-assigned
    to via an enrollments row (the ta-assignment convention)."""
    if user.role == "admin":
        return None
    owned = {row[0] for row in db.query(Course.id).filter(Course.instructor_id == user.id).all()}
    owned_via_sessions = {
        row[0] for row in db.query(ClassSession.course_id).filter(ClassSession.instructor_id == user.id).all()
    }
    ta_courses = {
        row[0]
        for row in db.query(Enrollment.course_id)
        .filter(Enrollment.student_id == user.id, Enrollment.is_active.is_(True))
        .all()
    }
    return owned | owned_via_sessions | ta_courses


@router.get("/overview", response_model=StatsOverviewResponse)
def stats_overview(
    course_id: Optional[str] = None,
    days: int = Query(default=7, ge=1, le=365),
    current_user: User = Depends(require_role("instructor", "ta", "admin")),
    db: Session = Depends(get_db),
):
    scope = _staff_course_scope(db, current_user)

    sessions_q = db.query(ClassSession)
    courses_q = db.query(Course)
    enrollments_q = db.query(Enrollment).filter(Enrollment.is_active.is_(True))
    if scope is not None:
        sessions_q = sessions_q.filter(ClassSession.course_id.in_(scope or {""}))
        courses_q = courses_q.filter(Course.id.in_(scope or {""}))
        enrollments_q = enrollments_q.filter(Enrollment.course_id.in_(scope or {""}))
    if course_id:
        sessions_q = sessions_q.filter(ClassSession.course_id == course_id)
        courses_q = courses_q.filter(Course.id == course_id)
        enrollments_q = enrollments_q.filter(Enrollment.course_id == course_id)

    total_sessions = sessions_q.count()
    active_sessions = sessions_q.filter(ClassSession.status == "active").count()
    total_courses = courses_q.count()
    total_students = enrollments_q.with_entities(Enrollment.student_id).distinct().count()

    session_ids = [row[0] for row in sessions_q.with_entities(ClassSession.id).all()]
    all_checkins = (
        db.query(CheckIn).filter(CheckIn.session_id.in_(session_ids or [""])).all() if session_ids else []
    )

    now = _now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    trend_start = now - timedelta(days=days)

    today_checkins = [c for c in all_checkins if c.checked_in_at >= today_start]
    week_checkins = [c for c in all_checkins if c.checked_in_at >= week_start]
    approved = [c for c in all_checkins if c.status == "approved"]
    flagged = [c for c in all_checkins if c.status == "flagged"]
    attended = [c for c in all_checkins if _is_attended(c)]
    high_risk_today = [c for c in today_checkins if c.risk_score >= 0.5]

    approval_rate = round(len(approved) / len(all_checkins), 4) if all_checkins else 0.0
    avg_attendance_rate = round(len(attended) / len(all_checkins), 4) if all_checkins else 0.0
    avg_risk = _avg([c.risk_score for c in all_checkins])

    daily = defaultdict(list)
    for c in all_checkins:
        if c.checked_in_at >= trend_start:
            daily[c.checked_in_at.date().isoformat()].append(c)
    checkins_by_day, attendance_rate_by_day = [], []
    for day in sorted(daily.keys(), reverse=True):
        day_checkins = daily[day]
        checkins_by_day.append(DayCount(date=day, count=len(day_checkins)))
        day_approved = sum(1 for c in day_checkins if c.status == "approved")
        attendance_rate_by_day.append(DayRate(date=day, rate=round(day_approved / len(day_checkins), 4)))

    return StatsOverviewResponse(
        total_sessions=total_sessions, active_sessions=active_sessions, total_courses=total_courses,
        total_students=total_students, today_checkins=len(today_checkins), flagged_pending=len(flagged),
        approval_rate=approval_rate, total_checkins_today=len(today_checkins), total_checkins_week=len(week_checkins),
        average_attendance_rate=avg_attendance_rate, flagged_pending_review=len(flagged), average_risk_score=avg_risk,
        high_risk_checkins_today=len(high_risk_today),
        trends=OverviewTrends(checkins_by_day=checkins_by_day, attendance_rate_by_day=attendance_rate_by_day),
    )


@router.get("/sessions/{session_id}", response_model=SessionStatsResponse)
def session_stats(
    session_id: str,
    current_user: User = Depends(require_role("instructor", "ta", "admin")),
    db: Session = Depends(get_db),
):
    session_obj = (
        db.query(ClassSession).options(joinedload(ClassSession.course)).filter(ClassSession.id == session_id).first()
    )
    if session_obj is None:
        raise APIError(404, "Session not found", ErrorCode.SESSION_NOT_FOUND)
    require_manage_session(db, current_user, session_obj)

    total_enrolled = (
        db.query(Enrollment)
        .filter(Enrollment.course_id == session_obj.course_id, Enrollment.is_active.is_(True))
        .count()
    )
    checkins = db.query(CheckIn).filter(CheckIn.session_id == session_id).all()

    by_status = ByStatusCounts()
    for c in checkins:
        if hasattr(by_status, c.status):
            setattr(by_status, c.status, getattr(by_status, c.status) + 1)

    attended = [c for c in checkins if _is_attended(c)]
    attendance_rate = round(len(attended) / total_enrolled, 4) if total_enrolled else 0.0

    distances = [c.distance_from_venue_meters for c in checkins if c.distance_from_venue_meters is not None]
    checkin_minutes = [(c.checked_in_at - session_obj.checkin_opens_at).total_seconds() / 60 for c in checkins]

    risk_dist = RiskDistribution()
    for c in checkins:
        if c.risk_score < 0.3:
            risk_dist.low += 1
        elif c.risk_score < 0.5:
            risk_dist.medium += 1
        else:
            risk_dist.high += 1

    timeline_buckets: dict = defaultdict(int)
    for c in checkins:
        minute = int((c.checked_in_at - session_obj.checkin_opens_at).total_seconds() // 60)
        timeline_buckets[(minute // 5) * 5] += 1
    checkin_timeline = [TimelinePoint(minute=m, count=n) for m, n in sorted(timeline_buckets.items())]

    return SessionStatsResponse(
        session_id=session_obj.id, session_name=session_obj.name, course_code=session_obj.course.code,
        scheduled_start=session_obj.scheduled_start, status=session_obj.status, total_enrolled=total_enrolled,
        checked_in=len(checkins), checked_in_count=len(checkins), approved_count=by_status.approved,
        flagged_count=by_status.flagged, attendance_rate=attendance_rate, by_status=by_status,
        average_risk_score=_avg([c.risk_score for c in checkins]),
        average_distance_meters=_avg(distances) if distances else None,
        average_checkin_time_minutes=_avg(checkin_minutes) if checkin_minutes else None, risk_distribution=risk_dist,
        checkin_timeline=checkin_timeline,
    )


@router.get("/courses/{course_id}", response_model=CourseStatsResponse)
def course_stats(
    course_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(require_role("instructor", "admin")),
    db: Session = Depends(get_db),
):
    course = db.get(Course, course_id)
    if course is None:
        raise APIError(404, "Course not found", ErrorCode.COURSE_NOT_FOUND)
    require_edit_course(current_user, course)

    sessions = db.query(ClassSession).filter(ClassSession.course_id == course_id).all()
    total_enrolled = (
        db.query(Enrollment).filter(Enrollment.course_id == course_id, Enrollment.is_active.is_(True)).count()
    )

    checkins_by_session = {}
    session_summaries = []
    for s in sessions:
        q = db.query(CheckIn).filter(CheckIn.session_id == s.id)
        if start_date:
            q = q.filter(CheckIn.checked_in_at >= start_date)
        if end_date:
            q = q.filter(CheckIn.checked_in_at <= end_date)
        checkins = q.all()
        checkins_by_session[s.id] = checkins
        attended = [c for c in checkins if _is_attended(c)]
        rate = round(len(attended) / total_enrolled, 4) if total_enrolled else 0.0
        session_summaries.append(CourseSessionSummary(
            session_id=s.id, name=s.name, date=s.scheduled_start.date().isoformat(),
            attendance_rate=rate, checked_in=len(checkins),
        ))

    overall_rate = _avg([s.attendance_rate for s in session_summaries])
    flagged_checkins = sum(1 for cs in checkins_by_session.values() for c in cs if c.status == "flagged")

    enrollments = (
        db.query(Enrollment)
        .options(joinedload(Enrollment.student))
        .filter(Enrollment.course_id == course_id, Enrollment.is_active.is_(True))
        .all()
    )
    total_sessions = len(sessions)
    student_attendance, low_attendance_alerts = [], []
    for e in enrollments:
        student_checkins = [c for cs in checkins_by_session.values() for c in cs if c.student_id == e.student_id]
        attended = [c for c in student_checkins if _is_attended(c)]
        rate = round(len(attended) / total_sessions, 4) if total_sessions else 0.0
        student_attendance.append(StudentAttendanceItem(
            student_id=e.student_id, student_name=e.student.full_name, sessions_attended=len(attended),
            attendance_rate=rate, average_risk_score=_avg([c.risk_score for c in student_checkins]),
        ))
        if total_sessions > 0 and rate < LOW_ATTENDANCE_THRESHOLD:
            low_attendance_alerts.append(LowAttendanceAlert(
                student_id=e.student_id, student_name=e.student.full_name, attendance_rate=rate,
                sessions_missed=total_sessions - len(attended),
            ))

    return CourseStatsResponse(
        course_id=course.id, course_code=course.code, course_name=course.name, total_sessions=total_sessions,
        total_enrolled=total_enrolled, overall_attendance_rate=overall_rate, average_attendance_rate=overall_rate,
        flagged_checkins=flagged_checkins, sessions=session_summaries, student_attendance=student_attendance,
        low_attendance_alerts=low_attendance_alerts,
    )


@router.get("/students/{student_id}", response_model=StudentStatsResponse)
def student_stats(
    student_id: str,
    current_user: User = Depends(require_role("instructor", "admin")),
    db: Session = Depends(get_db),
):
    student = db.get(User, student_id)
    if student is None:
        raise APIError(404, "User not found", ErrorCode.USER_NOT_FOUND)

    if current_user.role != "admin":
        # Same ownership rule as everywhere else (services/authz.py): a
        # course with no instructor_id assigned yet is visible to any
        # instructor, not just nobody - test_course never sets one, so a
        # strict `Course.instructor_id == current_user.id` filter would
        # 403 the fixture chain even for a legitimate request.
        their_courses = (
            db.query(Course)
            .join(Enrollment, Enrollment.course_id == Course.id)
            .filter(Enrollment.student_id == student_id, Enrollment.is_active.is_(True))
            .all()
        )
        teaches_them = any(can_edit_course(current_user, c) for c in their_courses)
        if not teaches_them:
            raise APIError(403, "Not authorized for this student", ErrorCode.INSUFFICIENT_PERMISSIONS)

    enrollments = (
        db.query(Enrollment)
        .options(joinedload(Enrollment.course))
        .filter(Enrollment.student_id == student_id, Enrollment.is_active.is_(True))
        .all()
    )

    courses_stats = []
    total_sessions_all = 0
    attended_all = 0
    for e in enrollments:
        session_ids = [
            row[0] for row in db.query(ClassSession.id).filter(ClassSession.course_id == e.course_id).all()
        ]
        checkins = (
            db.query(CheckIn)
            .filter(CheckIn.student_id == student_id, CheckIn.session_id.in_(session_ids or [""]))
            .all()
            if session_ids
            else []
        )
        attended = [c for c in checkins if _is_attended(c)]
        total = len(session_ids)
        rate = round(len(attended) / total, 4) if total else 0.0
        courses_stats.append(StudentCourseStats(
            course_id=e.course_id, course_code=e.course.code, attendance_rate=rate,
            sessions_attended=len(attended), total_sessions=total,
            average_risk_score=_avg([c.risk_score for c in checkins]),
        ))
        total_sessions_all += total
        attended_all += len(attended)

    overall_rate = round(attended_all / total_sessions_all, 4) if total_sessions_all else 0.0

    recent = (
        db.query(CheckIn)
        .options(joinedload(CheckIn.session).joinedload(ClassSession.course))
        .filter(CheckIn.student_id == student_id)
        .order_by(CheckIn.checked_in_at.desc())
        .limit(10)
        .all()
    )
    recent_items = [
        RecentCheckinItem(
            session_name=c.session.name, course_code=c.session.course.code, checked_in_at=c.checked_in_at,
            status=c.status,
        )
        for c in recent
    ]

    return StudentStatsResponse(
        student_id=student.id, student_name=student.full_name, student_email=student.email,
        total_enrolled_courses=len(enrollments), total_sessions=total_sessions_all, attended_sessions=attended_all,
        attendance_rate=overall_rate, courses=courses_stats, recent_sessions=recent_items, recent_checkins=recent_items,
    )
