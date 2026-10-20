"""Exports: attendance for the gradebook as CSV (opens in Excel), JSON or PDF."""
from __future__ import annotations

import streamlit as st

import api
import auth
import ui
from views import export_tools
from views.sessions import visible_sessions


def render() -> None:
    ui.header("EXPORTS", "Export attendance", "Download attendance for a whole course or one session.")
    scopes = ["Session"] + (["Course"] if auth.can("export_course") else [])
    scope = st.radio("Export", scopes, horizontal=True) if len(scopes) > 1 else "Session"

    if scope == "Course":
        courses = ui.safe(auth.my_courses, default=[])
        course = ui.pick("Course", courses, ui.course_label, key="export-course")
        if course:
            st.caption("Every check-in in the course, oldest first. Only the course's own instructor "
                       "(or an admin) can export it.")
            export_tools.course_export(course)
        return

    sessions = visible_sessions(ui.safe(api.get_all, "/api/v1/sessions/", default=[]))
    session = ui.pick("Session", sessions, ui.session_label, key="export-session")
    if session:
        export_tools.session_export(session)
