"""Sessions: create, activate and close sessions, and watch one session live
(attendance, risk breakdown, every check-in)."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pandas as pd
import streamlit as st

import api
import auth
import config
import ui
from views import export_tools

NTU_LAT, NTU_LON = 1.3483, 103.6831  # default venue (CHANGES doc: test location)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _manageable_courses() -> list[dict]:
    """Courses this user may create sessions in. Backend rule: admin, the
    course's instructor, or any instructor for a course with no instructor."""
    return ui.safe(auth.my_courses, default=[])


def visible_sessions(sessions: list[dict]) -> list[dict]:
    """The list endpoint returns every session; keep the ones this user works
    on: in their courses, or (instructors) created by them."""
    scope = ui.safe(auth.my_course_ids, default=set())
    if scope is None:
        return sessions
    me = auth.user().get("id")
    own = auth.role() == "instructor"
    return [s for s in sessions if (own and s.get("instructor_id") == me) or s.get("course_id") in scope]


def _sessions(status: str | None, course_id: str | None) -> list[dict]:
    sessions = ui.safe(api.get_all, "/api/v1/sessions/", status=status, course_id=course_id, default=[])
    return visible_sessions(sessions)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def _to_utc(day, clock: time) -> str:
    local = datetime.combine(day, clock, tzinfo=config.LOCAL_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def _create_form() -> None:
    courses = ui.safe(auth.creatable_courses, default=[])
    if not courses:
        st.info("You don't manage any course yet. An admin needs to assign you to a course first.")
        return
    with st.form("create-session", clear_on_submit=False, border=False):
        course = ui.pick("Course", courses, ui.course_label, key="new-session-course")
        left, right = st.columns(2)
        name = left.text_input("Session name", placeholder="Week 9 Lecture")
        session_type = right.selectbox("Type", ["lecture", "tutorial", "lab", "exam"])
        now = datetime.now(config.LOCAL_TZ) + timedelta(minutes=30)
        day = left.date_input("Date", value=now.date(), min_value=datetime.now(config.LOCAL_TZ).date())
        start = right.time_input("Starts", value=now.time().replace(second=0, microsecond=0), step=300)
        duration = left.number_input("Duration (minutes)", 15, 480, 120, step=15)
        venue = right.text_input("Venue", placeholder="LT26")
        st.markdown("**Location and security**")
        with st.container(border=True):
            a, b, c = st.columns(3)
            lat = a.number_input("Venue latitude", -90.0, 90.0, NTU_LAT, format="%.4f")
            lon = b.number_input("Venue longitude", -180.0, 180.0, NTU_LON, format="%.4f")
            radius = c.number_input("Geofence radius (m)", 20, 2000, 100, step=10)
            a, b, c = st.columns(3)
            opens_before = a.number_input("Check-in opens (min before start)", 0, 120, 15, step=5)
            closes_after = b.number_input("Check-in closes (min after start)", 5, 240, 30, step=5)
            liveness = c.toggle("Require liveness check", value=True)
            face = c.toggle("Require face match", value=False)
        submitted = st.form_submit_button("Create session", type="primary")

    if not submitted:
        return
    if not course or not name.strip():
        st.warning("Choose a course and enter a session name.")
        return
    start_local = datetime.combine(day, start, tzinfo=config.LOCAL_TZ)
    if start_local < datetime.now(config.LOCAL_TZ) - timedelta(minutes=5):
        st.warning("The start time is in the past. Sessions must start in the future.")
        return
    end_local = start_local + timedelta(minutes=int(duration))
    body = {
        "course_id": course["id"], "name": name.strip(), "session_type": session_type,
        "scheduled_start": _to_utc(day, start),
        "scheduled_end": end_local.astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
        "checkin_opens_at": (start_local - timedelta(minutes=int(opens_before))).astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
        "checkin_closes_at": (start_local + timedelta(minutes=int(closes_after))).astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
        "venue_name": venue.strip() or None, "venue_latitude": lat, "venue_longitude": lon,
        "geofence_radius_meters": float(radius), "require_liveness_check": liveness, "require_face_match": face,
    }
    created = ui.safe(api.post, "/api/v1/sessions/", body)
    if created:
        st.session_state.selected_session_id = created["id"]
        ui.flash(f"Session “{created['name']}” created. Activate it when class starts.", "✅")
        st.rerun()


# ---------------------------------------------------------------------------
# Status changes
# ---------------------------------------------------------------------------

ACTIONS = {
    # current status: [(button label, new status, confirmation text)]
    "scheduled": [("Activate check-in", "active", "Students will be able to check in now."),
                  ("Cancel session", "cancelled", "The session will be marked cancelled.")],
    "active": [("Close check-in", "closed", "No more check-ins will be accepted.")],
}


@st.dialog("Confirm")
def _confirm_status(session: dict, new_status: str, message: str) -> None:
    st.write(f"**{session['name']}** → {ui.status_label(new_status)}")
    st.caption(message)
    left, right = st.columns(2)
    if left.button("Confirm", type="primary", use_container_width=True):
        if ui.safe(api.patch, f"/api/v1/sessions/{session['id']}", {"status": new_status}) is not None:
            ui.flash(f"Session is now {new_status}.", "✅")
            st.rerun()
    if right.button("Back", use_container_width=True):
        st.rerun()


# ---------------------------------------------------------------------------
# One session
# ---------------------------------------------------------------------------

def _session_detail(session: dict) -> None:
    st.subheader(session["name"], anchor=False)
    st.caption(
        f"{session.get('course_code') or ''} · {session.get('session_type', '').title()} · "
        f"{ui.fmt_time(session.get('scheduled_start'))} → {ui.fmt_time(session.get('scheduled_end'), '%H:%M')} · "
        f"check-in {ui.fmt_time(session.get('checkin_opens_at'), '%H:%M')}–{ui.fmt_time(session.get('checkin_closes_at'), '%H:%M')}"
        f"{' · ' + session['venue_name'] if session.get('venue_name') else ''}"
    )
    status_col, *buttons = st.columns([2, 1, 1])
    status_col.markdown(f"Status: **{ui.status_label(session.get('status'))}**")
    if auth.can("manage_sessions"):
        for column, (label, new_status, message) in zip(buttons, ACTIONS.get(session.get("status"), [])):
            if column.button(label, key=f"{new_status}-{session['id']}", use_container_width=True,
                             type="primary" if new_status == "active" else "secondary"):
                _confirm_status(session, new_status, message)

    def live_part() -> None:
        stats = ui.safe(api.get, f"/api/v1/stats/sessions/{session['id']}")
        if not stats:
            return
        avg = stats.get("average_risk_score")
        ui.metric_row([
            ("Enrolled", stats.get("total_enrolled", 0), None),
            ("Checked in", stats.get("checked_in_count", 0), "Every check-in, including rejected ones."),
            ("Attendance", ui.pct(stats.get("attendance_rate")), "Rejected check-ins don't count as attended."),
            ("Flagged", stats.get("flagged_count", 0), "Waiting for review."),
            ("Average risk", "—" if avg is None else f"{avg:.2f}", "0 = no risk signals, 1 = maximum."),
        ])
        by_status, by_risk, timeline = st.columns(3)
        with by_status:
            st.markdown("**Check-ins by outcome**")
            frame = pd.DataFrame([{"status": k, "count": v} for k, v in (stats.get("by_status") or {}).items()])
            if frame.empty or frame["count"].sum() == 0:
                st.caption("No check-ins yet.")
            else:
                ui.bar_chart(frame, "status", "count", "Outcome", "Check-ins", colour_by="status")
        with by_risk:
            st.markdown("**Risk level**")
            frame = pd.DataFrame([{"level": k, "count": v} for k, v in (stats.get("risk_distribution") or {}).items()])
            if frame.empty or frame["count"].sum() == 0:
                st.caption("No check-ins yet.")
            else:
                ui.bar_chart(frame, "level", "count", "Risk (low < 0.3 ≤ medium < 0.5 ≤ high)", "Check-ins",
                             colour_by="level")
        with timeline:
            st.markdown("**Arrivals over time**")
            frame = pd.DataFrame(stats.get("checkin_timeline") or [])
            if frame.empty:
                st.caption("No check-ins yet.")
            else:
                ui.bar_chart(frame, "minute", "count", "Minutes after check-in opened", "Check-ins")

        st.markdown("**Check-ins**")
        checkins = ui.safe(api.get, f"/api/v1/checkins/session/{session['id']}", default=[]) or []
        if not checkins:
            st.caption("Nobody has checked in yet.")
        else:
            frame = pd.DataFrame([{
                "Student": c.get("student_name"), "Email": c.get("student_email"),
                "Checked in": c.get("checked_in_at"), "Status": ui.status_label(c.get("status")),
                "Risk": ui.risk_label(c.get("risk_level"), c.get("risk_score")),
                "Distance (m)": c.get("distance_from_venue_meters"),
                "Why": ui.reasons(c.get("risk_factors")),
            } for c in sorted(checkins, key=lambda c: c.get("checked_in_at") or "", reverse=True)])
            ui.local_datetime_column(frame, "Checked in")
            st.dataframe(frame, hide_index=True, use_container_width=True, column_config={
                "Checked in": st.column_config.DatetimeColumn(format="HH:mm:ss"),
                "Distance (m)": st.column_config.NumberColumn(format="%.0f"),
                "Why": st.column_config.TextColumn(width="large"),
            })
        if stats.get("flagged_count") and auth.can("review"):
            st.page_link(st.session_state.pages["review"], label=f"Review {stats['flagged_count']} flagged check-in(s) →")

    ui.live(live_part)

    with st.expander("Export this session"):
        export_tools.session_export(session)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def render() -> None:
    ui.header("SESSIONS", "Sessions", "Create sessions, open and close check-in, and follow attendance live.")

    if auth.can("manage_sessions"):
        with st.expander("➕ Create a session", expanded=False):
            _create_form()

    left, right = st.columns(2)
    status = left.selectbox("Status", ["All", "active", "scheduled", "closed", "cancelled"],
                            format_func=lambda s: s if s == "All" else ui.status_label(s))
    courses = _manageable_courses()
    course = right.selectbox("Course", [None] + [c["id"] for c in courses],
                             format_func=lambda cid: "All courses" if cid is None else ui.course_label(
                                 next(c for c in courses if c["id"] == cid)))
    sessions = _sessions(None if status == "All" else status, course)

    if not sessions:
        st.info("No sessions match. Create one above, or change the filters.")
        return

    frame = pd.DataFrame([{
        "id": s["id"], "Session": s.get("name"), "Course": s.get("course_code"),
        "Starts": s.get("scheduled_start"), "Status": ui.status_label(s.get("status")),
        "Checked in": f"{s.get('checked_in_count') or 0} / {s.get('total_enrolled') or 0}",
    } for s in sessions])
    ui.local_datetime_column(frame, "Starts")
    st.caption("Select a row to open the session.")
    event = st.dataframe(
        frame.drop(columns=["id"]), hide_index=True, use_container_width=True,
        on_select="rerun", selection_mode="single-row", key="sessions-table",
        column_config={"Starts": st.column_config.DatetimeColumn(format="ddd D MMM, HH:mm")},
    )
    selected_rows = event.selection.rows if event and event.selection else []
    if selected_rows:
        st.session_state.selected_session_id = frame.iloc[selected_rows[0]]["id"]

    selected = next((s for s in sessions if s["id"] == st.session_state.get("selected_session_id")), None)
    if selected is None and st.session_state.get("selected_session_id"):
        # Opened from Today but filtered out here: load it directly.
        selected = ui.safe(api.get, f"/api/v1/sessions/{st.session_state.selected_session_id}")
    if selected:
        st.divider()
        _session_detail(selected)
