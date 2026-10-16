"""Course analytics: attendance per session, per student, and students who
need attention (below 75% attendance)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api
import auth
import ui


def render() -> None:
    ui.header("COURSES", "Course analytics", "Attendance across a course's sessions and students.")
    courses = ui.safe(auth.my_courses, default=[])
    if not courses:
        st.info("You don't have any courses yet.")
        return
    course = ui.pick("Course", courses, ui.course_label, key="courses-pick")
    if not course:
        return

    stats = ui.safe(api.get, f"/api/v1/stats/courses/{course['id']}")
    if not stats:
        return
    alerts = stats.get("low_attendance_alerts") or []
    ui.metric_row([
        ("Sessions", stats.get("total_sessions", 0), None),
        ("Enrolled", stats.get("total_enrolled", 0), None),
        ("Attendance", ui.pct(stats.get("average_attendance_rate")), "Rejected check-ins don't count."),
        ("Flagged check-ins", stats.get("flagged_checkins", 0), None),
        ("Below 75%", len(alerts), "Students whose attendance is under 75%."),
    ])

    st.subheader("Attendance per session", anchor=False)
    sessions = pd.DataFrame(stats.get("sessions") or [])
    if sessions.empty:
        st.caption("No sessions yet.")
    else:
        sessions["date"] = pd.to_datetime(sessions["date"], errors="coerce")
        sessions = sessions.sort_values("date")
        sessions["date"] = sessions["date"].dt.strftime("%d %b") + " · " + sessions["name"]
        ui.line_chart(sessions, "date", "attendance_rate", "Session", "Attendance", percent=True,
                      colour=ui.GOOD)

    left, right = st.columns([1, 1.4])
    with left:
        st.subheader("Needs attention", anchor=False)
        if not alerts:
            st.success("Every student is at 75% attendance or above.", icon="✅")
        else:
            frame = ui.as_percent(pd.DataFrame(alerts), "attendance_rate").rename(columns={
                "student_name": "Student", "attendance_rate": "Attendance", "sessions_missed": "Missed"})
            st.dataframe(frame[["Student", "Attendance", "Missed"]], hide_index=True, use_container_width=True,
                         column_config={"Attendance": ui.PERCENT_BAR})
    with right:
        st.subheader("All students", anchor=False)
        students = pd.DataFrame(stats.get("student_attendance") or [])
        if students.empty:
            st.caption("No students enrolled.")
        else:
            frame = ui.as_percent(students, "attendance_rate").rename(columns={
                "student_name": "Student", "sessions_attended": "Attended", "attendance_rate": "Attendance",
                "average_risk_score": "Avg risk"}).sort_values("Attendance")
            st.dataframe(frame[["Student", "Attended", "Attendance", "Avg risk"]], hide_index=True,
                         use_container_width=True, column_config={
                             "Attendance": ui.PERCENT_BAR,
                             "Avg risk": st.column_config.NumberColumn(format="%.2f")})
