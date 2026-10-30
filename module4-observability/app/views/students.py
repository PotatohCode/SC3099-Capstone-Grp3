"""Student insights: pick a course and a student from lists (no IDs to type)
to see their attendance across your courses and recent check-ins."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api
import auth
import ui

RESET_ERRORS = {
    "FACE_NOT_ENROLLED": "This student hasn't registered a face yet, so no code is needed: "
                         "they can register their face in the app's Settings.",
    "STUDENT_NOT_FOUND": "This student account doesn't exist or is deactivated.",
    "INSUFFICIENT_PERMISSIONS": "Only an instructor of one of this student's courses (or an admin) "
                                "can issue a face reset code.",
    "FACE_RESET_CODE_UNAVAILABLE": "The code service is temporarily unavailable. Please try again.",
}


def _face_reset(student: dict) -> None:
    """One-time code that lets a student replace their registered face in the app.
    Shown once; generating a new one replaces the previous code."""
    st.subheader("Face reset code", anchor=False)
    st.caption("The student types this code in the app to register a new face. It works once and expires; "
               "it can't be shown again, and generating a new one cancels the previous code.")
    if student.get("face_enrolled") is False:
        st.info("This student hasn't registered a face yet, so no code is needed.", icon="ℹ️")
        return
    key = f"reset-code-{student['id']}"
    issued = st.session_state.get(key)
    if issued:
        with st.container(border=True):
            st.markdown("Give this code to the student **now**. It won't be shown again.")
            st.code(issued["code"], language=None)
            st.caption(f"Expires {ui.fmt_time(issued.get('expires_at'))} (Singapore time).")
            if st.button("Done, I've given the code to the student", key=f"{key}-done"):
                del st.session_state[key]
                st.rerun()
        return
    checked = st.checkbox("I've checked the student's card and they are who they say they are",
                          key=f"{key}-checked")
    st.caption("This matters: the code is what stops someone who only knows the password from "
               "swapping in their own face.")
    if st.button("Generate code", type="primary", disabled=not checked, key=f"{key}-go"):
        try:
            st.session_state[key] = api.post(f"/api/v1/users/{student['id']}/face/reset-code")
        except api.ApiError as err:
            if isinstance(err, api.SessionExpired) or err.code not in RESET_ERRORS:
                ui.show_error(err)
            else:
                st.warning(RESET_ERRORS[err.code], icon="⚠️")
        else:
            st.rerun()


def _student_options() -> list[dict]:
    if auth.role() == "admin":
        search = st.text_input("Search all students", placeholder="Name or email")
        users = ui.safe(api.get_all, "/api/v1/users/", role="student", search=search or None, default=[])
        return [{"id": u["id"], "name": u["full_name"], "email": u["email"],
                 "face_enrolled": u.get("face_enrolled")} for u in users]
    courses = ui.safe(auth.my_courses, default=[])
    course = ui.pick("Course", courses, ui.course_label, key="students-course")
    if not course:
        return []
    roster = ui.safe(api.get, f"/api/v1/enrollments/course/{course['id']}", role="student") or {}
    return [{"id": s["student_id"], "name": s["student_name"], "email": s["student_email"],
             "face_enrolled": s.get("face_enrolled")} for s in roster.get("students", [])]


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

    if auth.can("face_reset"):
        st.divider()
        _face_reset(student)
