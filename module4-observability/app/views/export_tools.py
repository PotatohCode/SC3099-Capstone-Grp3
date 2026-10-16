"""Export widgets shared by the Sessions and Exports pages.

Data is fetched only when the user clicks "Prepare export", because every
backend export call writes a `data_exported` audit entry."""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

import api
import exports
import ui


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text or "export").strip("-").lower()[:60]


def _absentees(course_id: str, present_ids: set[str], session: dict) -> list[dict]:
    roster = api.get(f"/api/v1/enrollments/course/{course_id}")
    date = ui.fmt_time(session.get("scheduled_start"), "%Y-%m-%d")
    return [{
        "student_id": s["student_id"], "student_name": s["student_name"], "student_email": s["student_email"],
        "session_date": date, "session_name": session.get("name"), "status": "absent",
        "checked_in_at": None, "risk_score": None,
    } for s in roster.get("students", []) if s["student_id"] not in present_ids]


def _downloads(key: str, report_rows: list[dict], filename: str, title: str, summary: dict[str, str],
               meta: dict) -> None:
    st.success(f"{len(report_rows)} record(s) ready.")
    a, b, c = st.columns(3)
    a.download_button("⬇ CSV (Excel)", exports.to_csv(report_rows), f"{filename}.csv", "text/csv",
                      key=f"{key}-csv", use_container_width=True)
    b.download_button("⬇ JSON", exports.to_json(report_rows, meta), f"{filename}.json", "application/json",
                      key=f"{key}-json", use_container_width=True)
    c.download_button("⬇ PDF report", exports.to_pdf(report_rows, title, summary), f"{filename}.pdf",
                      "application/pdf", key=f"{key}-pdf", use_container_width=True)
    if report_rows:
        preview = pd.DataFrame(report_rows)[exports.COLUMNS[:-1]].rename(columns=exports.HEADINGS)
        st.dataframe(preview, hide_index=True, use_container_width=True)


def session_export(session: dict) -> None:
    key = f"export-session-{session['id']}"
    include_absent = st.toggle("Include students who didn't check in", value=True, key=f"{key}-absent")
    if st.button("Prepare export", key=f"{key}-go"):
        try:
            data = api.get(f"/api/v1/export/session/{session['id']}", format="json")
            records = list(data.get("records", []))
            if include_absent:
                records += _absentees(session["course_id"], {r["student_id"] for r in records}, session)
            st.session_state[key] = {"records": records, "summary": data.get("summary", {})}
        except api.ApiError as err:
            ui.show_error(err)
    prepared = st.session_state.get(key)
    if not prepared:
        return
    summary = prepared["summary"]
    report_rows = exports.rows(prepared["records"], session.get("course_code") or "")
    _downloads(
        key, report_rows, f"attendance-{_slug(session.get('course_code'))}-{_slug(session['name'])}",
        f"Attendance · {session.get('course_code') or ''} · {session['name']}",
        {"Session date": ui.fmt_time(session.get("scheduled_start")),
         "Enrolled": str(summary.get("total_enrolled", "—")),
         "Checked in": str(summary.get("checked_in_count", "—")),
         "Attendance rate": ui.pct(summary.get("attendance_rate")),
         "Flagged": str(summary.get("flagged_count", "—"))},
        {"session_id": session["id"], "session_name": session["name"],
         "course": session.get("course_code"), "summary": summary},
    )


def course_export(course: dict) -> None:
    key = f"export-course-{course['id']}"
    if st.button("Prepare export", key=f"{key}-go"):
        try:
            st.session_state[key] = api.get(f"/api/v1/export/attendance/{course['id']}", format="json") or []
        except api.ApiError as err:
            ui.show_error(err)
    records = st.session_state.get(key)
    if records is None:
        return
    report_rows = exports.rows(records, course.get("code") or "")
    attended = sum(1 for r in report_rows if r["status"] not in ("rejected", "absent"))
    _downloads(
        key, report_rows, f"attendance-{_slug(course.get('code'))}",
        f"Attendance · {course.get('code')} · {course.get('name')}",
        {"Course": ui.course_label(course), "Semester": course.get("semester") or "—",
         "Check-ins": str(len(report_rows)), "Counted as attended": str(attended)},
        {"course_id": course["id"], "course": course.get("code"), "course_name": course.get("name")},
    )
