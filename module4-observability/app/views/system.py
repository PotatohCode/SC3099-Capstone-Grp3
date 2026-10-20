"""System health (admin): the few numbers that matter, read from Prometheus,
plus a link to Grafana for the detailed charts and alerts. Business numbers
first, technical ones second (Module 4 design deck)."""
from __future__ import annotations

import streamlit as st

import api
import config
import ui

WINDOW = "1h"

QUERIES = {
    # Business / security (last hour)
    "flagged_rate": f"sum(increase(checkins_flagged_total[{WINDOW}])) / sum(increase(checkin_attempts_total[{WINDOW}]))",
    "attempts": f"sum(increase(checkin_attempts_total[{WINDOW}]))",
    "failed_logins": f"sum(increase(login_failed_total[{WINDOW}]))",
    "lockouts": f"sum(increase(account_lockouts_total[{WINDOW}]))",
    "geo_blocked": f"sum(increase(checkin_rejected_geo_total[{WINDOW}]))",
    "violations": f"sum(increase(security_violations_total[{WINDOW}]))",
    # Technical (last 5 minutes)
    "p95_ms": "histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m]))) * 1000",
    "error_rate": 'sum(rate(http_request_duration_seconds_count{status_code=~"5.."}[5m])) / sum(rate(http_request_duration_seconds_count[5m]))',
    "backend_up": 'max(up{job="saiv-backend"})',
    "face_up": 'max(up{job="saiv-face-recognition"})',
}


def _num(value, fmt: str = "{:.0f}") -> str:
    return "—" if value is None else fmt.format(value)


def render() -> None:
    ui.header("SYSTEM", "System health", f"Live numbers from Prometheus. Detailed charts and alerts are in Grafana.")
    st.link_button("Open Grafana dashboards ↗", f"{config.GRAFANA_PUBLIC_URL}/dashboards", type="primary")

    def live_part() -> None:
        v = {name: api.prometheus_value(q) for name, q in QUERIES.items()}
        if all(value is None for value in v.values()):
            st.error("Prometheus is unreachable, so live numbers aren't available.", icon="⚠️")
            return
        st.subheader("Attendance and security · last hour", anchor=False)
        flagged = v["flagged_rate"]
        ui.metric_row([
            ("Check-in attempts", _num(v["attempts"]), None),
            ("Flagged rate", "—" if flagged is None else f"{flagged:.0%}",
             "Share of check-in attempts flagged for review. A sudden rise may mean a problem."),
            ("Failed sign-ins", _num(v["failed_logins"]), "Includes attempts on locked accounts."),
            ("Accounts locked", _num(v["lockouts"]), "Locked after 10 failed sign-ins in a row."),
            ("Outside Singapore", _num(v["geo_blocked"]), "Check-ins refused for location."),
            ("Security violations", _num(v["violations"]), "Replay, spoofing, impossible travel and more."),
        ])
        if flagged is not None and flagged > 0.3:
            st.warning("More than 30% of check-ins were flagged in the last hour. Check the review queue.", icon="🚨")
        if (v["failed_logins"] or 0) >= 20:
            st.warning("Many failed sign-ins in the last hour: possible password-guessing attack.", icon="🚨")

        st.subheader("Services · last 5 minutes", anchor=False)
        up = {1.0: "🟢 Up", 0.0: "🔴 Down"}
        error_rate = v["error_rate"]
        ui.metric_row([
            ("Backend", up.get(v["backend_up"], "⚪ Unknown"), None),
            ("Face service", up.get(v["face_up"], "⚪ Unknown"),
             "Shows Down until the face service exposes /metrics."),
            ("Response time (p95)", "—" if v["p95_ms"] is None else f"{v['p95_ms']:.0f} ms",
             "95% of requests are faster than this."),
            ("Server errors", "—" if error_rate is None else f"{error_rate:.1%}", "Share of 5xx responses."),
        ])

    ui.live(live_part)
