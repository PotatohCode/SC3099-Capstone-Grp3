"""Review queue: flagged and appealed check-ins, highest risk first, with the
reasons in plain words and approve / reject decisions."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

import api
import config
import ui


def _load() -> list[dict]:
    items = ui.safe(api.get_all, "/api/v1/checkins/flagged", default=[])
    return sorted(items, key=lambda c: (c.get("status") != "appealed", -(c.get("risk_score") or 0)))


@st.dialog("Review check-in")
def _decide(item: dict, decision: str) -> None:
    verb = "Approve" if decision == "approved" else "Reject"
    st.write(f"**{verb}** {item.get('student_name')}'s check-in for **{item.get('session_name')}**?")
    st.caption("Approved counts as attended. Rejected doesn't, and the student can appeal.")
    notes = st.text_area("Note (recorded in the audit log)", max_chars=2000,
                         placeholder="e.g. Verified in person after class")
    left, right = st.columns(2)
    if left.button(verb, type="primary", use_container_width=True):
        done = ui.safe(api.post, f"/api/v1/checkins/{item['id']}/review",
                       {"status": decision, "review_notes": notes.strip() or None})
        if done:
            st.session_state.pop("review_items", None)
            ui.flash(f"Check-in {decision}.", "✅" if decision == "approved" else "🚫")
            st.rerun()
    if right.button("Cancel", use_container_width=True):
        st.rerun()


def _card(item: dict) -> None:
    with st.container(border=True):
        top, actions = st.columns([4, 1.4])
        with top:
            badge = "🗨️ Appealed" if item.get("status") == "appealed" else ui.status_label("flagged")
            st.markdown(f"**{item.get('student_name')}** · {item.get('session_name')} &nbsp; {badge}")
            st.caption(f"Checked in {ui.fmt_time(item.get('checked_in_at'))} · "
                       f"risk {ui.risk_label(item.get('risk_level'), item.get('risk_score'))}")
            st.markdown("**Why it was flagged:** " + ui.reasons(item.get("risk_factors")))
            if item.get("appeal_reason"):
                st.markdown("**Student's appeal:**")
                st.text(item["appeal_reason"])  # plain text: never rendered as HTML
        with actions:
            if st.button("Approve", key=f"approve-{item['id']}", type="primary", use_container_width=True):
                _decide(item, "approved")
            if st.button("Reject", key=f"reject-{item['id']}", use_container_width=True):
                _decide(item, "rejected")


def render() -> None:
    ui.header("REVIEW QUEUE", "Flagged check-ins",
              "Appeals first, then highest risk. Your decision is recorded in the audit log.")

    refresh = st.button("↻ Refresh queue")
    if refresh or "review_items" not in st.session_state:
        st.session_state.review_items = _load()
        st.session_state.review_loaded_at = datetime.now(config.LOCAL_TZ)
    items = st.session_state.review_items

    # Poll for new items without disturbing the list being reviewed.
    def new_items_notice() -> None:
        latest = ui.safe(api.get, "/api/v1/checkins/flagged", limit=1)
        total = (latest or {}).get("total", len(items))
        if total > len(items):
            st.warning(f"{total - len(items)} new check-in(s) need review. Click **Refresh queue**.", icon="🔔")
    ui.live(new_items_notice)

    if not items:
        st.success("Nothing to review. All check-ins are resolved.", icon="✅")
        return

    sessions = sorted({i.get("session_name") for i in items})
    chosen = st.multiselect("Sessions", sessions, placeholder="All sessions")
    shown = [i for i in items if not chosen or i.get("session_name") in chosen]
    high = sum(1 for i in shown if (i.get("risk_level") or "").upper() in {"HIGH", "CRITICAL"})
    ui.metric_row([
        ("Waiting", len(shown), None),
        ("Appeals", sum(1 for i in shown if i.get("status") == "appealed"), "Students asking you to reconsider."),
        ("High risk", high, "Risk score 0.5 or above."),
    ])
    for item in shown:
        _card(item)
    st.caption(f"Loaded {st.session_state.review_loaded_at:%H:%M:%S}.")
