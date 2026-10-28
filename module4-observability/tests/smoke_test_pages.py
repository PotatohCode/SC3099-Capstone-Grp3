"""Smoke test: sign in as each role and open every page that role can see,
against the real backend. Fails on any exception or error message.

Needs the seeded demo accounts (scripts/seed_demo_data.py). Run inside the
dashboard container:

    docker compose exec dashboard python tests/smoke_test_pages.py
"""
from __future__ import annotations

import sys

import requests
from streamlit.testing.v1 import AppTest

sys.path.insert(0, "app")
import config  # noqa: E402

PASSWORD = "SaivDemo2026!"
ROLES = {
    "admin": ("admin@saiv.demo", ["today", "review", "sessions", "courses", "students", "exports",
                                  "accounts", "audit", "system"]),
    "instructor": ("instructor@saiv.demo", ["today", "review", "sessions", "courses", "students",
                                            "exports", "accounts"]),
    "ta": ("ta@saiv.demo", ["today", "review", "sessions", "exports"]),
}


def harness(page_key: str) -> None:
    """Same pages as main.py, with the page under test as the default."""
    import sys
    sys.path.insert(0, "app")
    import streamlit as st
    from views import accounts, audit, courses, exports_page, overview, review, sessions, students, system

    renders = {"today": overview.render, "review": review.render, "sessions": sessions.render,
               "courses": courses.render, "students": students.render, "exports": exports_page.render,
               "accounts": accounts.render, "audit": audit.render, "system": system.render}
    pages = {key: st.Page(fn, title=key, url_path=key, default=key == page_key) for key, fn in renders.items()}
    st.session_state.pages = pages
    st.navigation(list(pages.values())).run()


PICKERS = ("Course", "Student", "Session")


def _problems(app: AppTest, step: str) -> list[str]:
    return ([f"{step} exception: {e.value}" for e in app.exception]
            + [f"{step} error: {e.value}" for e in app.error])


def check(payload: dict, page: str, demo: bool = False, choices: dict | None = None) -> list[str]:
    app = AppTest.from_function(harness, args=(page,), default_timeout=90)
    app.session_state["access_token"] = payload["access_token"]
    app.session_state["refresh_token"] = payload.get("refresh_token")
    app.session_state["user"] = payload["user"]
    app.session_state["demo"] = demo
    app.session_state["live_updates"] = False
    app.run()
    problems = _problems(app, "open")
    # Then choose the seeded course / student / session, as a user would.
    for label in PICKERS:
        value = (choices or {}).get(label)
        boxes = [b for b in app.selectbox if b.label == label]
        if value and boxes and not problems:
            boxes[0].set_value(value).run()
            problems += _problems(app, f"pick {label.lower()}")
    return problems


def seeded_choices(token: str) -> dict:
    """IDs of the seeded SC3099 course, one of its students and its newest session."""
    headers = {"Authorization": f"Bearer {token}"}
    get = lambda path, **params: requests.get(f"{config.BACKEND_URL}/api/v1{path}", params=params,
                                              headers=headers, timeout=30)
    course, offset = None, 0
    while course is None:  # the list is capped at 100 per page
        page = get("/courses/", limit=100, offset=offset).json()
        course = next((c for c in page["items"] if c["code"] == "SC3099"), None)
        offset += len(page["items"])
        if course is None and (not page["items"] or offset >= page["total"]):
            raise SystemExit("Seeded course SC3099 not found: run scripts/seed_demo_data.py first")
    choices = {"Course": course["id"]}
    roster = get(f"/enrollments/course/{course['id']}")
    if roster.ok and roster.json()["students"]:
        choices["Student"] = roster.json()["students"][0]["student_id"]
    sessions = [s for s in get("/sessions/", course_id=course["id"], limit=50).json()["items"]
                if s["status"] != "scheduled"]
    if sessions:
        choices["Session"] = sessions[0]["id"]
    return choices


def check_session_detail(payload: dict, session_id: str) -> list[str]:
    app = AppTest.from_function(harness, args=("sessions",), default_timeout=90)
    for key in ("access_token", "refresh_token", "user"):
        app.session_state[key] = payload[key]
    app.session_state["demo"] = False
    app.session_state["live_updates"] = False
    app.session_state["selected_session_id"] = session_id
    app.run()
    problems = _problems(app, "session detail")
    prepare = [b for b in app.button if b.label == "Prepare export"]
    if prepare and not problems:
        prepare[0].click().run()
        problems += _problems(app, "session export")
    return problems


def main() -> int:
    failures = 0
    for role, (email, pages) in ROLES.items():
        response = requests.post(f"{config.BACKEND_URL}/api/v1/auth/login",
                                 json={"email": email, "password": PASSWORD}, timeout=30)
        response.raise_for_status()
        payload = response.json()
        choices = seeded_choices(payload["access_token"])
        for page in pages:
            problems = check(payload, page, choices=choices)
            print(f"[{'OK ' if not problems else 'FAIL'}] {role:<10} {page}")
            for problem in problems:
                print(f"         {problem[:400]}")
            failures += bool(problems)
        # The seeded SC3099 course's newest session, opened in detail + exported.
        sessions = requests.get(f"{config.BACKEND_URL}/api/v1/sessions/", params={"limit": 50},
                                headers={"Authorization": f"Bearer {payload['access_token']}"}, timeout=30).json()
        seeded = [s for s in sessions["items"] if s.get("course_code") == "SC3099" and s["status"] != "scheduled"]
        if seeded:
            problems = check_session_detail(payload, seeded[0]["id"])
            print(f"[{'OK ' if not problems else 'FAIL'}] {role:<10} session detail + export")
            for problem in problems:
                print(f"         {problem[:400]}")
            failures += bool(problems)
    demo_user = {"access_token": "preview", "user": {"id": "demo-instructor", "full_name": "Demo Instructor",
                                                     "email": "instructor@saiv.demo", "role": "instructor"}}
    for page in ROLES["instructor"][1]:
        problems = check(demo_user, page, demo=True)
        print(f"[{'OK ' if not problems else 'FAIL'}] preview    {page}")
        for problem in problems:
            print(f"         {problem[:400]}")
        failures += bool(problems)
    print(f"\n{failures} page(s) with problems")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
