"""Check-ins: search every check-in across sessions (GET /checkins/, scoped by
the backend to the courses this user works on) and open one for its full
details (GET /checkins/{id})."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pandas as pd
import streamlit as st

import api
import auth
import config
import ui

STATUSES = ["approved", "flagged", "appealed", "rejected", "pending"]


def _utc(day, clock: time) -> str:
    return datetime.combine(day, clock, tzinfo=config.LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def _yes_no(value, score=None) -> str:
    if value is None:
        return "Not checked"
    text = "✅ Passed" if value else "❌ Failed"
    return f"{text} ({score:.2f})" if score is not None else text


def _detail(row: dict) -> None:
    checkin = ui.safe(api.get, f"/api/v1/checkins/{row['id']}")
    if not checkin:
        return
    with st.container(border=True):
        st.markdown(f"**{ui.md(row.get('student_name'))}** · {ui.md(row.get('student_email'))} · "
                    f"{ui.md(row.get('session_name'))}")
        ui.metric_row([
            ("Status", ui.status_label(checkin.get("status")), None),
            ("How", ui.entry_label(checkin.get("entry_method")), None),
            ("Risk", ui.risk_label(checkin.get("risk_level"), checkin.get("risk_score")),
             "How suspicious the check-in looked (0 = no signals). The outcome also depends on the location, "
             "face and liveness checks."),
            ("Distance", "—" if checkin.get("distance_from_venue_meters") is None
             else f"{checkin['distance_from_venue_meters']:.0f} m", "From the venue pin."),
        ])
        st.markdown("**Why:** " + ui.reasons(checkin.get("risk_factors")))
        accuracy = checkin.get("location_accuracy_meters")
        lines = [
            f"Checked in **{ui.fmt_time(checkin.get('checked_in_at'))}**",
            f"Liveness: **{_yes_no(checkin.get('liveness_passed'), checkin.get('liveness_score'))}**",
            f"Face match: **{_yes_no(checkin.get('face_match_passed'), checkin.get('face_match_score'))}**",
            f"Location accuracy: **{'—' if accuracy is None else f'±{accuracy:.0f} m'}**",
            f"Device: **{'registered' if checkin.get('device_id') else 'none recorded'}**",
        ]
        st.markdown(" · ".join(lines))
        if checkin.get("reviewed_at"):
            st.markdown(f"**Reviewed** {ui.fmt_time(checkin['reviewed_at'])}"
                        + (":" if checkin.get("review_notes") else ""))
            if checkin.get("review_notes"):
                st.text(checkin["review_notes"])  # plain text: never rendered as HTML
        if checkin.get("appeal_reason"):
            st.markdown(f"**Student's appeal** ({ui.fmt_time(checkin.get('appealed_at'))}):")
            st.text(checkin["appeal_reason"])
        left, right, _ = st.columns([1, 1, 2])
        if left.button("Open session →", use_container_width=True, key=f"ci-open-{checkin['id']}"):
            st.session_state.selected_session_id = checkin["session_id"]
            st.switch_page(st.session_state.pages["sessions"])
        if checkin.get("status") in ("flagged", "appealed") and auth.can("review"):
            right.page_link(st.session_state.pages["review"], label="Review it in the queue →")


def render() -> None:
    ui.header("CHECK-INS", "Check-ins",
              "Search every check-in in the courses you work on, across sessions. Open one for the full details.")
    courses = ui.safe(auth.my_courses, default=[])
    by_id = {c["id"]: c for c in courses}
    a, b, c = st.columns([1.5, 1, 1])
    course = a.selectbox("Course", [None] + list(by_id), key="ci-course",
                         format_func=lambda cid: "All my courses" if cid is None else ui.course_label(by_id[cid]))
    status = b.selectbox("Status", [None] + STATUSES, key="ci-status",
                         format_func=lambda s: "All" if s is None else ui.status_label(s))
    today = datetime.now(config.LOCAL_TZ).date()
    dates = c.date_input("Dates", (today - timedelta(days=6), today), max_value=today, key="ci-dates")
    d, e = st.columns([1.5, 2])
    search = d.text_input("Student name or email", key="ci-search")
    min_risk = e.slider("Minimum risk score", 0.0, 1.0, 0.0, 0.05, key="ci-risk")
    if not isinstance(dates, tuple) or len(dates) != 2:
        st.info("Pick a start and an end date.")
        return

    rows = ui.safe(api.get_all, "/api/v1/checkins/", course_id=course, status=status,
                   start_date=_utc(dates[0], time.min), end_date=_utc(dates[1], time.max),
                   min_risk_score=min_risk or None, default=[])
    needle = search.strip().lower()
    if needle:
        rows = [r for r in rows if needle in (r.get("student_name") or "").lower()
                or needle in (r.get("student_email") or "").lower()]
    counts = {s: sum(1 for r in rows if r.get("status") == s) for s in STATUSES}
    ui.metric_row([
        ("Check-ins", len(rows), None),
        ("Approved", counts["approved"], None),
        ("Flagged / appealed", counts["flagged"] + counts["appealed"], "Waiting for a staff decision."),
        ("Rejected", counts["rejected"], "Don't count as attended."),
    ])
    if not rows:
        st.info("No check-ins match. Change the filters or widen the dates.")
        return
    frame = pd.DataFrame([{
        "Checked in": r.get("checked_in_at"), "Student": r.get("student_name"), "Email": r.get("student_email"),
        "Session": r.get("session_name"), "Status": ui.status_label(r.get("status")),
        "How": ui.entry_label(r.get("entry_method")), "Risk": ui.risk_label(r.get("risk_level"), r.get("risk_score")),
        "Distance (m)": r.get("distance_from_venue_meters"),
    } for r in rows])
    ui.local_datetime_column(frame, "Checked in")
    event = st.dataframe(frame, hide_index=True, use_container_width=True, on_select="rerun",
                         selection_mode="single-row", key="ci-table",
                         column_config={"Checked in": st.column_config.DatetimeColumn(format="ddd D MMM, HH:mm"),
                                        "Distance (m)": st.column_config.NumberColumn(format="%.0f")})
    picked = event.selection.rows if event and event.selection else []
    if picked:
        _detail(rows[picked[0]])
    else:
        st.caption("Tick the box at the left of a row to see that check-in's full details.")
