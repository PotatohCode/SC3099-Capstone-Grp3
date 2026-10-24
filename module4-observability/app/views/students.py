"""Student insights: pick a course and a student from lists (no IDs to type)
to see their attendance across your courses and recent check-ins."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api
import auth
import ui


def _student_options() -> list[dict]:
    if auth.role() == "admin":
        search = st.text_input("Search all students", placeholder="Name or email")
        users = ui.safe(api.get_all, "/api/v1/users/", role="student", search=search or None, default=[])
        return [{"id": u["id"], "name": u["full_name"], "email": u["email"]} for u in users]
    courses = ui.safe(auth.my_courses, default=[])
    course = ui.pick("Course", courses, ui.course_label, key="students-course")
    if not course:
        return []
    roster = ui.safe(api.get, f"/api/v1/enrollments/course/{course['id']}", role="student") or {}
    return [{"id": s["student_id"], "name": s["student_name"], "email": s["student_email"]}
            for s in roster.get("students", [])]


def render() -> None:
    ui.header("STUDENTS", "Student insights", "One student's attendance across the courses you manage.")
    options = _student_options()
    if not options:
        st.caption("Choose a course to list its students." if auth.role() != "admin" else "No students found.")
        return
    student = ui.pick("Student", options, lambda s: f"{s['name']} · {s['email']}", key="students-pick")
    if not student:
        return

    stats = ui.safe(api.get, f"/api/v1/stats/students/{student['id']}")
    if not stats:
        return
    ui.metric_row([
        ("Courses", stats.get("total_enrolled_courses", 0), None),
        ("Sessions attended", f"{stats.get('attended_sessions', 0)} / {stats.get('total_sessions', 0)}", None),
        ("Attendance", ui.pct(stats.get("attendance_rate")), "Rejected check-ins don't count."),
    ])

    left, right = st.columns(2)
    with left:
        st.subheader("By course", anchor=False)
        frame = pd.DataFrame(stats.get("courses") or [])
        if frame.empty:
            st.caption("Not enrolled in any of your courses.")
        else:
            frame = ui.as_percent(frame, "attendance_rate").rename(columns={
                "course_code": "Course", "attendance_rate": "Attendance", "sessions_attended": "Attended",
                "total_sessions": "Sessions", "average_risk_score": "Avg risk"})
            st.dataframe(frame[["Course", "Attended", "Sessions", "Attendance", "Avg risk"]], hide_index=True,
                         use_container_width=True, column_config={
                             "Attendance": ui.PERCENT_BAR,
                             "Avg risk": st.column_config.NumberColumn(format="%.2f")})
    with right:
        st.subheader("Recent check-ins", anchor=False)
        recent = stats.get("recent_checkins") or stats.get("recent_sessions") or []
        if not recent:
            st.caption("No check-ins yet.")
        else:
            frame = pd.DataFrame([{
                "When": r.get("checked_in_at"), "Course": r.get("course_code"),
                "Session": r.get("session_name"), "Status": ui.status_label(r.get("status")),
            } for r in recent])
            ui.local_datetime_column(frame, "When")
            st.dataframe(frame, hide_index=True, use_container_width=True,
                         column_config={"When": st.column_config.DatetimeColumn(format="D MMM, HH:mm")})
