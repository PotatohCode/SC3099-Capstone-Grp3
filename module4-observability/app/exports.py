"""Attendance export files: CSV, JSON and PDF built from the backend's export
data (GET /export/... ?format=json, which also writes the backend's
`data_exported` audit entry).

Columns follow the Module 4 design deck: student name, email, course,
session date, check-in time, status, risk score."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from fpdf import FPDF

import config
import ui

COLUMNS = ["student_name", "student_email", "course", "session_date", "session_name",
           "checked_in_at", "status", "risk_score", "student_id"]
HEADINGS = {"student_name": "Student name", "student_email": "Email", "course": "Course",
            "session_date": "Session date", "session_name": "Session", "checked_in_at": "Check-in time",
            "status": "Status", "risk_score": "Risk score", "student_id": "Student ID"}

# Spreadsheet formula injection guard (same rule as the backend's CSV export).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def rows(records: list[dict], course_code: str) -> list[dict]:
    """Backend export records -> report rows with a course column and local times."""
    out = []
    for record in records:
        out.append({
            "student_name": record.get("student_name", ""),
            "student_email": record.get("student_email", ""),
            "course": course_code,
            "session_date": record.get("session_date", ""),
            "session_name": record.get("session_name", ""),
            "checked_in_at": ui.fmt_time(record.get("checked_in_at"), "%Y-%m-%d %H:%M") if record.get("checked_in_at") else "",
            "status": record.get("status") or "absent",
            "risk_score": "" if record.get("risk_score") is None else round(float(record["risk_score"]), 3),
            "student_id": record.get("student_id", ""),
        })
    return out


def to_csv(report_rows: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([HEADINGS[c] for c in COLUMNS])
    for row in report_rows:
        writer.writerow([safe_cell(row.get(c, "")) for c in COLUMNS])
    # UTF-8 with BOM so Excel shows non-English names correctly.
    return buffer.getvalue().encode("utf-8-sig")


def to_json(report_rows: list[dict], meta: dict) -> bytes:
    return json.dumps({**meta, "records": report_rows}, indent=2, ensure_ascii=False).encode("utf-8")


def _latin1(text) -> str:
    # Built-in PDF fonts only cover Latin-1; replace anything else.
    return str(text).encode("latin-1", "replace").decode("latin-1")


def to_pdf(report_rows: list[dict], title: str, summary: dict[str, str]) -> bytes:
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, _latin1(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    generated = datetime.now(config.LOCAL_TZ).strftime("%d %b %Y %H:%M SGT")
    pdf.cell(0, 6, _latin1(f"Generated {generated} · SAIV attendance record"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    for label, value in summary.items():
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(38, 6, _latin1(label))
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 6, _latin1(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    widths = {"student_name": 48, "student_email": 62, "course": 22, "session_date": 24,
              "session_name": 44, "checked_in_at": 30, "status": 22, "risk_score": 18}
    cols = list(widths)

    def table_header():
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(23, 48, 66)
        pdf.set_text_color(255, 255, 255)
        for col in cols:
            pdf.cell(widths[col], 7, _latin1(HEADINGS[col]), border=0, fill=True)
        pdf.ln()
        pdf.set_text_color(0, 0, 0)

    table_header()
    pdf.set_font("Helvetica", "", 8)
    for i, row in enumerate(report_rows):
        if pdf.will_page_break(6):
            pdf.add_page()
            table_header()
            pdf.set_font("Helvetica", "", 8)
        pdf.set_fill_color(244, 246, 244) if i % 2 else pdf.set_fill_color(255, 255, 255)
        for col in cols:
            text = _latin1(row.get(col, ""))
            max_chars = int(widths[col] / 1.7)
            pdf.cell(widths[col], 6, text if len(text) <= max_chars else text[: max_chars - 3] + "...", fill=True)
        pdf.ln()
    if not report_rows:
        pdf.cell(0, 8, "No attendance records.")
    return bytes(pdf.output())
