"""Today: the instructor's starting point. Most important first (top-left):
what needs action, then today's sessions, then trends."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pandas as pd
import streamlit as st

import api
import auth
import config
import ui


def _today_bounds_utc() -> tuple[str, str]:
    today = datetime.now(config.LOCAL_TZ).date()
    start = datetime.combine(today, time.min, tzinfo=config.LOCAL_TZ).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    return start.replace(tzinfo=None).isoformat(), end.replace(tzinfo=None).isoformat()


def _key_numbers() -> None:
    overview = ui.safe(api.get, "/api/v1/stats/overview", days=7)
    if not overview:
        return
    # The overview's flagged_pending counts `flagged` only; the review queue also
    # holds appeals, so use the queue's own total to keep the two in step.
    queue = ui.safe(api.get, "/api/v1/checkins/flagged", limit=1) or {}
    needs_review = queue.get("total", overview.get("flagged_pending", 0))
    left, *rest = st.columns([1.3, 1, 1, 1])
    with left:
        st.metric("Needs review", needs_review, border=True,
                  help="Flagged or appealed check-ins waiting for a decision.")
        if needs_review and auth.can("review"):
            st.page_link(st.session_state.pages["review"], label="Open review queue →")
    rest[0].metric("Today", overview.get("today_checkins", 0), border=True, help="Check-ins today.")
    rest[1].metric("Live", overview.get("active_sessions", 0), border=True,
                   help="Sessions currently open for check-in.")
    rest[2].metric("Attendance", ui.pct(overview.get("average_attendance_rate")), border=True,
                   help="Average over sessions held so far (active or closed): students who attended ÷ "
                        "students enrolled. Rejected (blocked) check-ins don't count as attended.")
    st.session_state["overview_trends"] = overview.get("trends", {})


def _todays_sessions() -> None:
    start, end = _today_bounds_utc()
    from views.sessions import visible_sessions
    sessions = visible_sessions(ui.safe(api.get_all, "/api/v1/sessions/", start_date=start, end_date=end, default=[]))
    st.subheader("Today's sessions", anchor=False)
    if not sessions:
        st.caption("No sessions scheduled today.")
        return
    order = {"active": 0, "scheduled": 1, "closed": 2, "cancelled": 3}
    sessions.sort(key=lambda s: (order.get(s.get("status"), 9), s.get("scheduled_start", "")))
    columns = st.columns(3)
    for index, session in enumerate(sessions):
        with columns[index % 3].container(border=True):
            st.markdown(f"**{ui.md(session.get('name'))}**")
            st.caption(f"{ui.md(session.get('course_code'))} · "
                       f"{ui.fmt_time(session.get('scheduled_start'), '%H:%M')}–"
                       f"{ui.fmt_time(session.get('scheduled_end'), '%H:%M')}"
                       f"{' · ' + ui.md(session['venue_name']) if session.get('venue_name') else ''}")
            enrolled = session.get("total_enrolled") or 0
            checked = session.get("checked_in_count") or 0
            st.markdown(f"{ui.status_label(session.get('status'))} &nbsp; **{checked}** / {enrolled} checked in")
            if enrolled:
                st.progress(min(checked / enrolled, 1.0))
            if st.button("Open session", key=f"open-{session['id']}", use_container_width=True):
                st.session_state.selected_session_id = session["id"]
                st.switch_page(st.session_state.pages["sessions"])


def _trends() -> None:
    trends = st.session_state.get("overview_trends") or {}
    left, right = st.columns(2)
    with left:
        st.subheader("Check-ins per day", anchor=False)
        frame = pd.DataFrame(trends.get("checkins_by_day", []))
        if frame.empty:
            st.caption("No check-ins in the last 7 days.")
        else:
            frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%a %d %b")
            ui.bar_chart(frame, "date", "count", "Date", "Check-ins")
    with right:
        st.subheader("Attendance rate per day", anchor=False)
        frame = pd.DataFrame(trends.get("attendance_rate_by_day", []))
        if frame.empty:
            st.caption("No attendance data in the last 7 days.")
        else:
            frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%a %d %b")
            ui.line_chart(frame, "date", "rate", "Date", "Attendance", percent=True, colour=ui.GOOD)


def render() -> None:
    name = (auth.user().get("full_name") or "there").split()[0]
    ui.header("TODAY", f"{ui.greeting()}, {name}.",
              "What needs your attention across the courses you manage.")

    def live_part() -> None:
        _key_numbers()
        _todays_sessions()
        _trends()
        st.caption(f"Updated {datetime.now(config.LOCAL_TZ):%H:%M:%S}"
                   + (f" · refreshes every {config.REFRESH_SECONDS}s" if st.session_state.live_updates else ""))

    ui.live(live_part)
