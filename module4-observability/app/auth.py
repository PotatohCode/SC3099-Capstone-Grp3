"""Sign-in, sign-out and what each role may do.

The backend enforces every permission; these checks only decide which pages
and buttons to show (Module 4 design deck: "hide UI elements user can't
access", but "backend must enforce permissions")."""
from __future__ import annotations

import streamlit as st

import api
import config

SESSION_KEYS = ("access_token", "refresh_token", "user", "demo")

# Which roles each role may create in the Accounts page.
CREATABLE_ROLES = {
    "admin": ["student", "ta", "instructor", "admin"],
    "instructor": ["student", "ta"],
}


def init_session() -> None:
    for key in SESSION_KEYS:
        st.session_state.setdefault(key, None)
    st.session_state.setdefault("live_updates", True)
    st.session_state.setdefault("login_notice", None)


def user() -> dict:
    return st.session_state.user or {}


def role() -> str:
    return user().get("role", "")


def is_signed_in() -> bool:
    return bool(st.session_state.access_token and st.session_state.user)


def can(action: str) -> bool:
    """UI permissions mirroring docs/API-SPECIFICATION.md's role table."""
    r = role()
    rules = {
        "manage_sessions": r in {"instructor", "admin"},      # create / activate / close
        "review": r in {"ta", "instructor", "admin"},
        "manual_checkin": r in {"ta", "instructor", "admin"},  # backend: staff who manage the session
        "face_reset": r in {"instructor", "admin"},          # backend: the student's instructor, or admin
        "course_analytics": r in {"instructor", "admin"},
        "student_analytics": r in {"instructor", "admin"},
        "manage_accounts": r in {"instructor", "admin"},
        "export_course": r in {"instructor", "admin"},
        "audit": r == "admin",
        "system": r == "admin",
    }
    return rules.get(action, False)


def my_course_ids() -> set[str] | None:
    """Courses this user works on (None = all, for admin). Cached per sign-in.

    instructor: courses they're assigned to (unassigned courses are only
    offered when creating a session, see creatable_courses). ta: courses
    whose roster the backend lets them read, i.e. the ones they're assigned to."""
    if role() == "admin":
        return None
    if st.session_state.get("scope_course_ids") is None:
        courses = api.get_all("/api/v1/courses/")
        if role() == "instructor":
            me = user().get("id")
            ids = {c["id"] for c in courses if c.get("instructor_id") == me}
        else:
            ids = set()
            for course in courses:
                try:
                    api.get(f"/api/v1/enrollments/course/{course['id']}")
                    ids.add(course["id"])
                except api.SessionExpired:
                    raise
                except api.ApiError:
                    pass
        st.session_state.scope_course_ids = ids
    return st.session_state.scope_course_ids


def my_courses() -> list[dict]:
    courses = api.get_all("/api/v1/courses/")
    scope = my_course_ids()
    return courses if scope is None else [c for c in courses if c["id"] in scope]


def creatable_courses() -> list[dict]:
    """Courses an instructor may add sessions/students to: their own, plus
    courses nobody is assigned to yet (the backend's ownership rule)."""
    courses = api.get_all("/api/v1/courses/")
    if role() == "admin":
        return courses
    me = user().get("id")
    own = [c for c in courses if c.get("instructor_id") == me]
    return own + [c for c in courses if c.get("instructor_id") is None]


def clear_session() -> None:
    for key in SESSION_KEYS:
        st.session_state[key] = None
    for key in [k for k in st.session_state.keys() if k not in SESSION_KEYS + ("live_updates", "login_notice")]:
        del st.session_state[key]


def sign_out() -> None:
    api.logout()
    clear_session()


def _start_demo() -> None:
    st.session_state.access_token = "preview"
    st.session_state.refresh_token = None
    st.session_state.user = {"id": "demo-instructor", "full_name": "Demo Instructor",
                             "email": "instructor@saiv.demo", "role": "instructor"}
    st.session_state.demo = True


def login_page() -> None:
    left, middle, right = st.columns([1, 2, 1])
    with middle:
        st.markdown('<div class="eyebrow">SAIV · SECURE ATTENDANCE</div>', unsafe_allow_html=True)
        st.title("Instructor portal", anchor=False)
        st.caption("Monitor sessions, review flagged check-ins and export attendance for grading.")

        if st.session_state.login_notice:
            st.warning(st.session_state.login_notice)

        with st.form("login", border=True):
            email = st.text_input("Staff email", placeholder="name@ntu.edu.sg")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

        if submitted:
            if not email or not password:
                st.warning("Enter both your email and password.")
            else:
                try:
                    payload = api.login(email.strip(), password)
                except api.ApiError as err:
                    st.error(str(err))
                else:
                    if payload["user"].get("role") not in config.STAFF_ROLES:
                        # Don't keep a student's tokens around.
                        st.session_state.access_token = payload["access_token"]
                        st.session_state.refresh_token = payload["refresh_token"]
                        api.logout()
                        clear_session()
                        st.error("This portal is for TAs, instructors and admins. "
                                 "Students check in through the SAIV app.")
                    else:
                        st.session_state.access_token = payload["access_token"]
                        st.session_state.refresh_token = payload["refresh_token"]
                        st.session_state.user = payload["user"]
                        st.session_state.demo = False
                        st.session_state.login_notice = None
                        st.rerun()

        if config.DEMO_MODE:
            st.divider()
            if st.button("Explore with sample data", use_container_width=True):
                _start_demo()
                st.rerun()
