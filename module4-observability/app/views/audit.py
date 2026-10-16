"""Audit log explorer (admin only). The log is append-only in the database:
this page reads and exports it, and never changes it."""
from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone

import pandas as pd
import streamlit as st

import api
import config
import exports
import ui

SECURITY_ACTIONS = ["security_violation", "account_locked", "login_failed", "checkin_rejected_geo",
                    "checkin_rejected"]


def _utc(day, end: bool = False) -> str:
    moment = datetime.combine(day, time.max if end else time.min, tzinfo=config.LOCAL_TZ)
    return moment.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def _summary(days: int) -> None:
    summary = ui.safe(api.get, "/api/v1/audit/summary", days=days)
    if not summary:
        return
    by_action = summary.get("by_action") or {}
    ui.metric_row([
        ("Events", summary.get("total_logs", 0), f"Last {days} days."),
        ("Failed", summary.get("failed_count", 0), "Events recorded as unsuccessful."),
        ("Security violations", by_action.get("security_violation", 0), None),
        ("Failed sign-ins", by_action.get("login_failed", 0), None),
        ("Accounts locked", by_action.get("account_locked", 0), None),
    ])
    if by_action:
        frame = pd.DataFrame([{"action": ui.AUDIT_ACTION_LABELS.get(k, k), "count": v}
                              for k, v in by_action.items()]).sort_values("count", ascending=False).head(12)
        ui.bar_chart(frame, "action", "count", "Event", "Count")


def render() -> None:
    ui.header("AUDIT", "Audit log", "Every security-relevant event. The log can't be edited or deleted.")
    days = st.select_slider("Summary period", [1, 7, 30, 90, 365], value=30, format_func=lambda d: f"{d} days")
    _summary(days)

    st.subheader("Explore events", anchor=False)
    a, b, c, d = st.columns([1.4, 1, 1, 1])
    actions = sorted(ui.AUDIT_ACTION_LABELS)
    action = a.selectbox("Event", [None] + actions, format_func=lambda x: "All events" if x is None
                         else ui.AUDIT_ACTION_LABELS.get(x, x))
    outcome = b.selectbox("Outcome", ["All", "Succeeded", "Failed"])
    today = datetime.now(config.LOCAL_TZ).date()
    start = c.date_input("From", today - timedelta(days=7))
    end = d.date_input("To", today)
    security_only = st.toggle("Security events only", help=", ".join(SECURITY_ACTIONS))

    params = {"action": action, "start_date": _utc(start), "end_date": _utc(end, end=True),
              "success": None if outcome == "All" else outcome == "Succeeded"}
    logs = ui.safe(api.get_all, "/api/v1/audit/", **params, default=[])
    if security_only:
        logs = [log for log in logs if log.get("action") in SECURITY_ACTIONS]
    if not logs:
        st.caption("No events match.")
        return

    frame = pd.DataFrame([{
        "When": log.get("timestamp"), "Event": ui.AUDIT_ACTION_LABELS.get(log.get("action"), log.get("action")),
        "OK": log.get("success"), "User": log.get("user_email") or "—",
        "Resource": f"{log.get('resource_type') or ''} {str(log.get('resource_id') or '')[:8]}".strip() or "—",
        "IP": log.get("ip_address") or "—",
        "Details": json.dumps(log.get("details") or {}, ensure_ascii=False),
    } for log in logs])
    ui.local_datetime_column(frame, "When")
    st.caption(f"{len(frame)} event(s), newest first.")
    st.dataframe(frame, hide_index=True, use_container_width=True, column_config={
        "When": st.column_config.DatetimeColumn(format="D MMM, HH:mm:ss"),
        "OK": st.column_config.CheckboxColumn(), "Details": st.column_config.TextColumn(width="large")})

    # Export for compliance audits (Briefing p.29).
    export = frame.copy()
    export["When"] = export["When"].astype(str)
    csv = export.map(exports.safe_cell).to_csv(index=False).encode("utf-8-sig")
    left, right = st.columns(2)
    left.download_button("⬇ Export CSV", csv, f"audit-log-{start}-{end}.csv", "text/csv", use_container_width=True)
    right.download_button("⬇ Export JSON", json.dumps(logs, indent=2, ensure_ascii=False).encode("utf-8"),
                          f"audit-log-{start}-{end}.json", "application/json", use_container_width=True)
