"""Shared look and helpers so every page is consistent (Module 4 design deck:
consistent layouts, colour with meaning, Y-axis from zero, clear labels)."""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable

import pandas as pd
import plotly.express as px
import streamlit as st

import api
import config

# Colour with meaning: green good, amber needs attention, red bad.
GOOD, WARN, BAD, NEUTRAL, INFO = "#15803d", "#d97706", "#b91c1c", "#64748b", "#0f766e"

STATUS_COLOURS = {
    "approved": GOOD, "pending": NEUTRAL, "flagged": WARN, "appealed": WARN, "rejected": BAD,
    "active": GOOD, "scheduled": INFO, "closed": NEUTRAL, "cancelled": BAD,
    "low": GOOD, "medium": WARN, "high": BAD,
}
STATUS_ICONS = {
    "approved": "🟢", "pending": "⚪", "flagged": "🟠", "appealed": "🟠", "rejected": "🔴",
    "active": "🟢", "scheduled": "🔵", "closed": "⚫", "cancelled": "🔴",
}
RISK_ICONS = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}

# Plain-language reasons for the backend's risk factor types
# (module2-backend/api-docs/CHANGES-2026-10-01.md section 5.3).
RISK_REASONS = {
    "geo_out_of_bounds": "Outside the classroom area",
    "geo_accuracy_low": "Location is imprecise (over 100 m)",
    "device_unknown": "Unregistered or untrusted device",
    "impossible_travel": "Impossible travel since last check-in",
    "liveness_failed": "Failed the liveness check",
    "liveness_unverified": "Liveness could not be verified",
    "liveness_challenge_failed": "Didn't complete the liveness challenge (all attempts)",
    "face_match_failed": "Face does not match the enrolled face",
    "face_match_unverified": "Face could not be verified",
    "replay_suspected": "Re-used photo (possible replay)",
    "gps_spoof_suspected": "Location looks faked (accuracy under 1 m)",
    "rapid_succession": "Device used by another student minutes ago",
    "unusual_time": "Checked in more than 15 min after start",
    "consent_missing": "Camera/location consent not given",
    "device_unbound": "Device not bound to this student",
    "manual_checkin": "Checked in manually by staff",
    "manual_override": "Approved by staff (manual override)",
}

AUDIT_ACTION_LABELS = {
    "login_success": "Signed in", "login_failed": "Failed sign-in", "logout": "Signed out",
    "account_locked": "Account locked", "user_created": "Account created", "user_updated": "Account updated",
    "user_deletion_requested": "Account deletion requested", "face_enrolled": "Face enrolled",
    "checkin_attempted": "Check-in attempted", "checkin_approved": "Check-in approved",
    "checkin_flagged": "Check-in flagged", "checkin_rejected": "Check-in rejected",
    "checkin_rejected_geo": "Check-in blocked (outside Singapore)", "checkin_appealed": "Check-in appealed",
    "checkin_reviewed": "Check-in reviewed",
    "liveness_challenge_verified": "Liveness challenge attempt",
    "face_reset_code_issued": "Face reset code issued", "face_reset_code_rejected": "Wrong face reset code",
    "face_reenrolled": "Face re-registered with a reset code",
    "checkin_manual": "Manual check-in by staff", "checkin_manual_override": "Check-in approved by staff (override)",
    "checkin_manual_undone": "Staff check-in undone",
    "password_changed": "Password changed", "password_change_failed": "Password change failed", "session_created": "Session created",
    "session_updated": "Session updated", "session_deleted": "Session deleted",
    "enrollment_added": "Enrolment added", "enrollment_removed": "Enrolment removed",
    "device_registered": "Device registered", "device_updated": "Device updated",
    "device_removed": "Device removed", "course_created": "Course created", "course_updated": "Course updated",
    "course_deleted": "Course deleted", "data_exported": "Data exported",
    "retention_sweep_run": "Retention clean-up", "security_violation": "Security violation",
}


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def flash(message: str, icon: str = "✅") -> None:
    """A confirmation that survives the st.rerun() that usually follows an action."""
    st.session_state.flash = (message, icon)


def header(eyebrow: str, title: str, caption: str | None = None) -> None:
    if st.session_state.get("flash"):
        message, icon = st.session_state.pop("flash")
        st.toast(message, icon=icon)
    st.markdown(f'<div class="eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.title(title, anchor=False)
    if caption:
        st.caption(caption)
    if st.session_state.get("demo"):
        st.info("Preview mode: you are looking at sample data, not live records.", icon="🧪")


def metric_row(items: Iterable[tuple[str, object, str | None]]) -> None:
    """items: (label, value, help text)."""
    items = list(items)
    for column, (label, value, help_text) in zip(st.columns(len(items)), items):
        column.metric(label, value, help=help_text, border=True)


def show_error(err: Exception) -> None:
    """Shows a readable error; sends the user back to sign-in if needed."""
    if isinstance(err, api.SessionExpired):
        import auth
        auth.clear_session()
        st.session_state.login_notice = str(err)
        st.rerun()
    st.error(str(err), icon="⚠️")


def safe(call: Callable, *args, default=None, **kwargs):
    """Runs an API call; on failure shows the error and returns `default`."""
    try:
        return call(*args, **kwargs)
    except api.ApiError as err:
        show_error(err)
        return default


def live(render: Callable[[], None]) -> None:
    """Runs `render` as a fragment that re-runs every REFRESH_SECONDS while
    live updates are switched on, without reloading the whole page."""
    interval = config.REFRESH_SECONDS if st.session_state.get("live_updates", True) else None
    st.fragment(render, run_every=interval)()


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def to_local(value) -> pd.Timestamp | None:
    """Backend timestamp (naive UTC string) -> Singapore time."""
    if value in (None, ""):
        return None
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(stamp) else stamp.tz_convert(config.LOCAL_TZ)


def fmt_time(value, pattern: str = "%d %b %Y, %H:%M") -> str:
    stamp = to_local(value)
    return stamp.strftime(pattern) if stamp is not None else "—"


def local_datetime_column(frame: pd.DataFrame, *columns: str) -> pd.DataFrame:
    """Converts timestamp columns to timezone-naive Singapore time for display."""
    for name in columns:
        if name in frame:
            # ISO8601: the backend sends some times with microseconds and some without;
            # pandas would otherwise guess one format from the first row and blank the rest.
            frame[name] = pd.to_datetime(frame[name], utc=True, errors="coerce", format="ISO8601").dt.tz_convert(
                config.LOCAL_TZ).dt.tz_localize(None)
    return frame


PERCENT_BAR = st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)


def as_percent(frame: pd.DataFrame, *columns: str) -> pd.DataFrame:
    """0–1 rates -> 0–100 for PERCENT_BAR columns."""
    frame = frame.copy()
    for name in columns:
        if name in frame:
            frame[name] = (pd.to_numeric(frame[name], errors="coerce") * 100).round(1)
    return frame


_MD_SPECIAL = "\\`*_{}[]()<>#+-.!|~:$"


def md(text) -> str:
    """User-entered text made safe inside st.markdown/st.subheader/captions:
    shown exactly as typed, never as formatting, links or HTML."""
    return "".join("\\" + ch if ch in _MD_SPECIAL else ch for ch in str(text or ""))


def pct(value) -> str:
    return "—" if value is None else f"{float(value):.0%}"


def status_label(status: str | None) -> str:
    status = (status or "").lower()
    return f"{STATUS_ICONS.get(status, '⚪')} {status.title()}" if status else "—"


def checkin_window(session: dict) -> str:
    """Where the check-in window is now: 'not_open', 'open' or 'closed'."""
    now = pd.Timestamp.now(tz=config.LOCAL_TZ)
    opens, closes = to_local(session.get("checkin_opens_at")), to_local(session.get("checkin_closes_at"))
    if opens is not None and now < opens:
        return "not_open"
    if closes is not None and now > closes:
        return "closed"
    return "open"


def _clock(stamp) -> str:
    """'17:15' today, otherwise '31 Oct 17:15'."""
    local = to_local(stamp)
    if local is None:
        return "—"
    today = pd.Timestamp.now(tz=config.LOCAL_TZ).date()
    return local.strftime("%H:%M" if local.date() == today else "%d %b %H:%M")


def checkin_state(session: dict) -> str:
    """Whether students can check in right now, in plain words. Students need
    both an active session and the current time inside the check-in window."""
    status = session.get("status")
    if status == "cancelled":
        return "—"
    if status == "closed":
        return "⛔ Closed"
    window = checkin_window(session)
    opens, closes = _clock(session.get("checkin_opens_at")), _clock(session.get("checkin_closes_at"))
    if status == "active":
        return {"open": f"🟢 Open now · closes {closes}", "not_open": f"⏳ Opens {opens}",
                "closed": f"⛔ Window ended {closes}"}[window]
    return {"open": f"🔵 Not activated · window open until {closes}", "not_open": f"🔵 Opens {opens} once activated",
            "closed": f"⛔ Window ended {closes}"}[window]


ENTRY_LABELS = {"app": "📱 App", "manual": "✍️ Manual", "override": "✅ Override"}


def entry_label(method: str | None) -> str:
    """How a check-in was made: the student's app, a staff manual check-in, or
    staff approving over the app's result."""
    return ENTRY_LABELS.get(method or "app", method or "")


def risk_label(level: str | None, score: float | None = None) -> str:
    level = (level or "").upper()
    icon = RISK_ICONS.get(level, "⚪")
    score_text = f" ({score:.2f})" if score is not None else ""
    return f"{icon} {level.title()}{score_text}" if level else "—"


SEVERITY_ICONS = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}


def reasons(factors: list | None) -> str:
    """Risk factors -> 'Outside the classroom area · Unregistered device'.
    Factors from the review queue carry a severity; those get an icon, worst first."""
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    factors = sorted(factors or [], key=lambda f: order.get(f.get("severity"), 4))
    names = []
    for f in factors:
        name = RISK_REASONS.get(f.get("type"), (f.get("type") or "").replace("_", " "))
        icon = SEVERITY_ICONS.get(f.get("severity"))
        names.append(f"{icon} {name}" if icon else name)
    return " · ".join(names) if names else "No risk signals"


def greeting(now: datetime | None = None) -> str:
    hour = (now or datetime.now(config.LOCAL_TZ)).hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"


# ---------------------------------------------------------------------------
# Charts (zero-based Y-axis, labelled axes, no chart junk)
# ---------------------------------------------------------------------------

def _finish(fig, y_title: str, percent: bool = False):
    fig.update_layout(
        margin=dict(l=8, r=8, t=8, b=8), height=280, showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_yaxes(rangemode="tozero", title=y_title, gridcolor="rgba(100,116,139,.2)",
                     tickformat=".0%" if percent else None, range=[0, 1.05] if percent else None)
    return fig


def bar_chart(frame: pd.DataFrame, x: str, y: str, x_title: str, y_title: str,
              colour_by: str | None = None) -> None:
    colours = STATUS_COLOURS if colour_by else None
    fig = px.bar(frame, x=x, y=y, color=colour_by, color_discrete_map=colours,
                 color_discrete_sequence=[INFO], text=y, labels={x: x_title, y: y_title})
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_xaxes(title=x_title)
    st.plotly_chart(_finish(fig, y_title), use_container_width=True, config={"displayModeBar": False})


def line_chart(frame: pd.DataFrame, x: str, y: str, x_title: str, y_title: str,
               percent: bool = False, colour: str = INFO) -> None:
    fig = px.line(frame, x=x, y=y, markers=True, color_discrete_sequence=[colour],
                  labels={x: x_title, y: y_title})
    fig.update_xaxes(title=x_title)
    st.plotly_chart(_finish(fig, y_title, percent), use_container_width=True, config={"displayModeBar": False})


# ---------------------------------------------------------------------------
# Location map
# ---------------------------------------------------------------------------

# Rough Singapore bounds. The backend refuses check-ins from outside Singapore,
# so a venue outside this box could never be checked in to.
SG_LAT, SG_LON = (1.15, 1.48), (103.6, 104.1)


def in_singapore(lat: float, lon: float) -> bool:
    return SG_LAT[0] <= lat <= SG_LAT[1] and SG_LON[0] <= lon <= SG_LON[1]


MAP_HEIGHT = 320
NTU_CENTRE = (1.3483, 103.6831)  # where a map starts when there's no pin yet


def venue_map(lat: float | None, lon: float | None, radius_m: float, label: str = ""):
    """The one map style used everywhere: OpenStreetMap, red pin, teal check-in circle."""
    import folium

    has_pin = lat is not None and lon is not None
    centre = (lat, lon) if has_pin else NTU_CENTRE
    zoom = (17 if radius_m <= 100 else 16 if radius_m <= 300 else 15 if radius_m <= 700 else 14) if has_pin else 16
    fmap = folium.Map(location=centre, zoom_start=zoom, control_scale=True)
    if has_pin:
        folium.Circle(centre, radius=float(radius_m), color="#0f766e", weight=2, fill=True, fill_opacity=0.15,
                      tooltip=f"Check-in radius: {radius_m:.0f} m").add_to(fmap)
        folium.Marker(centre, tooltip=label or "Venue", icon=folium.Icon(color="red", icon="map-marker")).add_to(fmap)
    return fmap


def location_caption(lat: float, lon: float, radius_m: float) -> None:
    st.caption(f"📍 {lat:.5f}, {lon:.5f} · students must be within **{radius_m:.0f} m** of the pin "
               f"([open in Google Maps](https://www.google.com/maps?q={lat},{lon})).")


def location_map(lat: float, lon: float, radius_m: float, label: str = "", *, key: str) -> None:
    """View-only venue map: drag and zoom to look around; clicks don't change anything."""
    from streamlit_folium import st_folium

    st_folium(venue_map(lat, lon, radius_m, label), key=key, height=MAP_HEIGHT, use_container_width=True,
              returned_objects=[])  # nothing returned, so moving the map doesn't reload the page
    location_caption(lat, lon, radius_m)


# ---------------------------------------------------------------------------
# Common pickers
# ---------------------------------------------------------------------------

def course_label(course: dict) -> str:
    return f"{course.get('code') or course.get('course_code', '')} · {course.get('name') or course.get('course_name', '')}"


def session_label(session: dict) -> str:
    return f"{session.get('course_code') or ''} · {session.get('name')} · {fmt_time(session.get('scheduled_start'), '%d %b %H:%M')}"


def pick(label: str, options: list[dict], format_func: Callable[[dict], str], key: str,
         placeholder: str = "Choose…") -> dict | None:
    """Selectbox over dicts keyed by id, so items with equal names stay distinct."""
    by_id = {o["id"]: o for o in options}
    chosen = st.selectbox(label, list(by_id), index=None, key=key, placeholder=placeholder,
                          format_func=lambda oid: format_func(by_id[oid]))
    return by_id.get(chosen)
