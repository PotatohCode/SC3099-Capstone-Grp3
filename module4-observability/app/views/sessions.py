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


def course_location(course: dict) -> tuple[float, float, float] | None:
    """The course's saved classroom (lat, lon, radius), or None if it has none."""
    if course.get("venue_latitude") is None or course.get("venue_longitude") is None:
        return None
    return course["venue_latitude"], course["venue_longitude"], float(course.get("geofence_radius_meters") or 100)


def _location_section(course: dict) -> dict | None:
    """Where students must be to check in. Returns the location fields for the
    request ({} = use the course's location), or None if it isn't valid yet.

    A session may leave its location empty: the backend then checks students
    against the course's location. If the course has none either there'd be no
    location check at all, so then the session's own location is required."""
    saved = course_location(course)
    key = course["id"]
    st.markdown("**Location** · where students must be to check in")
    if saved:
        choice = st.radio(
            "Location", ["course", "different"], key=f"loc-mode-{key}", horizontal=True,
            label_visibility="collapsed",
            format_func=lambda m: (f"Course location ({ui.md(course.get('venue_name') or 'classroom')})"
                                   if m == "course" else "A different location for this session"))
        if choice == "course":
            lat, lon, radius = saved
            ui.location_map(lat, lon, radius, course.get("venue_name") or "")
            # Send no coordinates: the backend uses the course's, and follows any later fix to them.
            return {"venue_name": course.get("venue_name")}
    else:
        st.warning("This course has no classroom location saved, so enter where this session takes place. "
                   "Without a location, students could check in from anywhere.", icon="📍")

    a, b, c, d = st.columns([1, 1, 0.8, 1.2])
    lat = a.number_input("Latitude", -90.0, 90.0, value=saved[0] if saved else None, format="%.6f",
                         placeholder="1.3483", key=f"loc-lat-{key}")
    lon = b.number_input("Longitude", -180.0, 180.0, value=saved[1] if saved else None, format="%.6f",
                         placeholder="103.6831", key=f"loc-lon-{key}")
    radius = c.number_input("Radius (m)", 20, 2000, int(saved[2]) if saved else 100, step=10, key=f"loc-r-{key}")
    venue = d.text_input("Venue name", placeholder="e.g. Exam Hall A", key=f"loc-name-{key}")
    st.caption("Tip: in Google Maps, right-click the room's building and click the coordinates to copy them.")
    if lat is None or lon is None:
        st.info("Enter the latitude and longitude to see the location on the map.")
        return None
    if not ui.in_singapore(lat, lon):
        st.error("Those coordinates are outside Singapore. The backend refuses check-ins from outside "
                 "Singapore, so nobody could check in. Check the numbers (latitude first).")
        return None
    ui.location_map(lat, lon, radius, venue)
    return {"venue_latitude": lat, "venue_longitude": lon, "geofence_radius_meters": float(radius),
            "venue_name": venue.strip() or None}


def _create_form() -> None:
    courses = ui.safe(auth.creatable_courses, default=[])
    if not courses:
        st.info("You don't manage any course yet. An admin needs to assign you to a course first.")
        return
    course = ui.pick("Course", courses, ui.course_label, key="new-session-course")
    if not course:
        return

    left, right = st.columns(2)
    name = left.text_input("Session name", placeholder="Week 9 Lecture", key="new-session-name")
    session_type = right.selectbox("Type", ["lecture", "tutorial", "lab", "exam"], key="new-session-type")
    soon = datetime.now(config.LOCAL_TZ) + timedelta(minutes=30)
    day = left.date_input("Date", value=soon.date(), min_value=datetime.now(config.LOCAL_TZ).date(),
                          key="new-session-day")
    start = right.time_input("Starts", value=soon.time().replace(second=0, microsecond=0), step=300,
                             key="new-session-start")
    duration = left.number_input("Duration (minutes)", 15, 480, 120, step=15, key="new-session-duration")
    a, b = right.columns(2)
    opens_before = a.number_input("Check-in opens (min before)", 0, 120, 15, step=5, key="new-session-opens")
    closes_after = b.number_input("Check-in closes (min after)", 5, 240, 30, step=5, key="new-session-closes")
    a, b = st.columns(2)
    liveness = a.toggle("Require liveness check", value=True, key="new-session-liveness")
    face = b.toggle("Require face match", value=False, key="new-session-face")

    location = _location_section(course)

    if not st.button("Create session", type="primary", disabled=location is None, key="new-session-create"):
        return
    if not name.strip():
        st.warning("Enter a session name.")
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
        "require_liveness_check": liveness, "require_face_match": face,
        **{k: v for k, v in location.items() if v is not None},
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
    st.write(f"**{ui.md(session['name'])}** → {ui.status_label(new_status)}")
    st.caption(message)
    left, right = st.columns(2)
    if left.button("Confirm", type="primary", use_container_width=True):
        if ui.safe(api.patch, f"/api/v1/sessions/{session['id']}", {"status": new_status}) is not None:
            ui.flash(f"Session is now {new_status}.", "✅")
            st.rerun()
    if right.button("Back", use_container_width=True):
        st.rerun()


# ---------------------------------------------------------------------------
# Manual check-in (staff check in a student who is in class but couldn't)
# ---------------------------------------------------------------------------

MANUAL_ERRORS = {
    "ALREADY_CHECKED_IN": "This student is already checked in (approved).",
    "SESSION_NOT_ACTIVE": "Check-in for this session hasn't opened yet, or the session was cancelled.",
    "MANUAL_CHECKIN_WINDOW_CLOSED": "Manual check-ins are only possible until 7 days after the session.",
    "NOT_ENROLLED": "This student isn't enrolled in the session's course.",
    "MANUAL_UNDO_NOT_ALLOWED": "Only manual check-ins and staff overrides can be undone.",
}


def _manual_error(err: api.ApiError) -> None:
    if isinstance(err, api.SessionExpired) or err.code not in MANUAL_ERRORS:
        ui.show_error(err)
    else:
        st.warning(MANUAL_ERRORS[err.code], icon="⚠️")


@st.dialog("Undo staff check-in")
def _confirm_undo(row: dict) -> None:
    manual = row.get("entry_method") == "manual"
    st.write(f"Undo the {'manual check-in' if manual else 'override'} for **{ui.md(row.get('student_name'))}**?")
    st.caption("The check-in is removed and the student is absent again (they can still check in themselves "
               "while check-in is open)." if manual else
               "The check-in goes back to exactly what it was before (for example flagged), "
               "with its original reviewer and notes.")
    left, right = st.columns(2)
    if left.button("Undo", type="primary", use_container_width=True):
        try:
            result = api.post(f"/api/v1/checkins/{row['id']}/manual/undo")
        except api.ApiError as err:
            _manual_error(err)
        else:
            status = (result or {}).get("status")
            ui.flash("Manual check-in removed." if status == "deleted" else f"Override undone: back to {status}.", "↩️")
            st.rerun()
    if right.button("Cancel", use_container_width=True):
        st.rerun()


def _manual_checkin(session: dict) -> None:
    st.caption("For a student who is in class but couldn't check in (phone dead, camera broken, GPS refused). "
               "If they already tried and were flagged or rejected, this approves that check-in instead. "
               "Possible until 7 days after the session; everything is recorded in the audit log.")
    roster = (ui.safe(api.get, f"/api/v1/enrollments/course/{session['course_id']}", role="student") or {}).get("students", [])
    checkins = ui.safe(api.get, f"/api/v1/checkins/session/{session['id']}", default=[]) or []
    by_student = {c["student_id"]: c for c in checkins}
    # Already-approved students can't be checked in again.
    options = [s for s in roster if (by_student.get(s["student_id"]) or {}).get("status") != "approved"]

    def label(s: dict) -> str:
        current = by_student.get(s["student_id"])
        state = f" · currently {current['status']}" if current else " · not checked in"
        return f"{s['student_name']} · {s['student_email']}{state}"

    if not options:
        st.success("Every enrolled student is already checked in.", icon="✅")
    else:
        by_id = {s["student_id"]: s for s in options}
        with st.form(f"manual-{session['id']}", clear_on_submit=True):
            student_id = st.selectbox("Student", list(by_id), index=None, placeholder="Choose a student…",
                                      format_func=lambda sid: label(by_id[sid]))
            reason = st.text_input("Reason (required, saved in the audit log)", max_chars=500,
                                   placeholder="e.g. Phone died, seen in class")
            submitted = st.form_submit_button("Check in", type="primary")
        if submitted:
            if not student_id or not reason.strip():
                st.warning("Choose a student and enter a reason.")
            else:
                try:
                    result = api.request("POST", "/api/v1/checkins/manual", raw=True, json={
                        "session_id": session["id"], "student_id": student_id, "reason": reason.strip()})
                except api.ApiError as err:
                    _manual_error(err)
                else:
                    name = by_id[student_id]["student_name"]
                    ui.flash(f"{name} checked in." if result.status_code == 201
                             else f"{name}'s earlier check-in is now approved (override).", "✍️")
                    st.rerun()

    staff_rows = [c for c in checkins if c.get("entry_method") in ("manual", "override")]
    if staff_rows:
        st.markdown("**Staff check-ins** · undo one if it was a mistake")
        for row in sorted(staff_rows, key=lambda c: c.get("checked_in_at") or "", reverse=True):
            name_col, how_col, button_col = st.columns([3, 1.2, 1])
            name_col.markdown(f"{ui.md(row.get('student_name'))} · {ui.fmt_time(row.get('checked_in_at'), '%d %b %H:%M')}")
            how_col.markdown(ui.entry_label(row.get("entry_method")))
            if button_col.button("Undo", key=f"undo-{row['id']}", use_container_width=True):
                _confirm_undo(row)


# ---------------------------------------------------------------------------
# One session
# ---------------------------------------------------------------------------

def _session_location(session: dict) -> None:
    """Where check-ins are measured: the session's own location, else the
    course's (same rule as the backend's services/geofencing.py)."""
    if session.get("venue_latitude") is not None and session.get("venue_longitude") is not None:
        radius = session.get("geofence_radius_meters")
        if radius is None:
            course = ui.safe(api.get, f"/api/v1/courses/{session['course_id']}") or {}
            radius = course.get("geofence_radius_meters") or 100
        st.caption("This session's own location.")
        ui.location_map(session["venue_latitude"], session["venue_longitude"], float(radius),
                        session.get("venue_name") or "")
        return
    course = ui.safe(api.get, f"/api/v1/courses/{session['course_id']}") or {}
    saved = course_location(course)
    if saved:
        st.caption(f"Uses the course's location ({ui.md(course.get('venue_name') or 'classroom')}).")
        ui.location_map(*saved, course.get("venue_name") or "")
    else:
        st.warning("Neither this session nor its course has a location, so students' locations "
                   "aren't checked against a classroom.", icon="📍")

def _session_detail(session: dict) -> None:
    st.subheader(ui.md(session["name"]), anchor=False)
    st.caption(
        f"{ui.md(session.get('course_code'))} · {session.get('session_type', '').title()} · "
        f"{ui.fmt_time(session.get('scheduled_start'))} → {ui.fmt_time(session.get('scheduled_end'), '%H:%M')} · "
        f"check-in {ui.fmt_time(session.get('checkin_opens_at'), '%H:%M')}–{ui.fmt_time(session.get('checkin_closes_at'), '%H:%M')}"
        f"{' · ' + ui.md(session['venue_name']) if session.get('venue_name') else ''}"
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
                "How": ui.entry_label(c.get("entry_method")),
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

    if auth.can("manual_checkin") and session.get("status") != "cancelled":
        with st.expander("✍️ Manual check-in"):
            _manual_checkin(session)

    with st.expander("Location"):
        _session_location(session)

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
