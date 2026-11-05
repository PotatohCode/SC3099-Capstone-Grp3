"""Sign-in, sign-out and what each role may do.

The backend enforces every permission; these checks only decide which pages
and buttons to show (Module 4 design deck: "hide UI elements user can't
access", but "backend must enforce permissions")."""
from __future__ import annotations

import hashlib
import json

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
        "manage": r == "admin",                              # users, courses, devices (admin-only endpoints)
        "delete_session": r in {"instructor", "admin"},      # backend: scheduled sessions only
        "checkin_search": r in {"ta", "instructor", "admin"},
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
            api.get("/api/v1/users/me")  # renews the access token first if it has expired
            ids = set(_ta_course_ids(user().get("id"), tuple(c["id"] for c in courses),
                                     st.session_state.access_token))
        st.session_state.scope_course_ids = ids
    return st.session_state.scope_course_ids


@st.cache_data(ttl=600, show_spinner="Loading your courses…")
def _ta_course_ids(user_id: str, course_ids: tuple[str, ...], _token: str) -> list[str]:
    """Courses a TA is assigned to. The backend has no "my courses" call for TAs,
    so this asks for each course's roster (allowed only for its own TAs). That's
    one request per course, so the answer is remembered for 10 minutes per TA,
    across sign-ins and tabs, instead of being rebuilt at every sign-in.
    (`_token` is left out of the cache key; the key is the TA and the course list.)"""
    mine = []
    for course_id in course_ids:
        response = api._send("GET", f"/api/v1/enrollments/course/{course_id}", token=_token)
        if response.status_code == 401:
            # Don't cache an answer built with a dead token.
            raise api.SessionExpired("Your session has expired. Please sign in again.", 401)
        if response.ok:
            mine.append(course_id)
    return mine


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
    # Signed out (or the login expired): forget the copy kept in the tab, and
    # don't try to restore from it on this page.
    st.session_state.restore_checked = True
    st.session_state.forget_saved_login = True


# ---------------------------------------------------------------------------
# Staying signed in across a browser refresh
#
# A refresh starts a new Streamlit session, which has no tokens. So the refresh
# token is also kept in the tab's sessionStorage (like the student app): on a
# fresh page it's read back and swapped for new tokens. sessionStorage belongs
# to this tab only and is cleared when the tab closes; sign-out removes it. The
# access token never leaves the server.
# ---------------------------------------------------------------------------

SAVED_LOGIN_KEY = "saiv_portal_refresh_token"
SAVED_PAGE_KEY = "saiv_portal_page"


def _js(expression: str, key: str):
    from streamlit_js_eval import streamlit_js_eval
    return streamlit_js_eval(js_expressions=expression, key=key)


def remember_login(page: str) -> None:
    """Keeps the tab's copy of the refresh token up to date (it changes at
    sign-in and when tokens are renewed), plus which page is open, so a refresh
    comes back to it."""
    token = st.session_state.refresh_token
    saved = (token, page)
    if st.session_state.get("demo") or not token or st.session_state.get("saved_login") == saved:
        return
    storage = "window.parent.sessionStorage"
    _js(f"{storage}.setItem({json.dumps(SAVED_LOGIN_KEY)}, {json.dumps(token)}); "
        f"{storage}.setItem({json.dumps(SAVED_PAGE_KEY)}, {json.dumps(page)}); 'saved'",
        key=f"save-login-{hashlib.sha256((token + page).encode()).hexdigest()[:16]}")
    st.session_state.saved_login = saved


def restore_login() -> None:
    """On a page with no sign-in: sign back in from the tab's saved refresh token,
    if there is one. Stops the page while the browser is asked (one quick rerun)."""
    storage = "window.parent.sessionStorage"
    if st.session_state.get("forget_saved_login"):
        _js(f"{storage}.removeItem({json.dumps(SAVED_LOGIN_KEY)}); {storage}.removeItem({json.dumps(SAVED_PAGE_KEY)}); "
            "'forgotten'", key=f"forget-login-{st.session_state.get('forget_round', 0)}")
        st.session_state.forget_saved_login = False
        st.session_state.forget_round = st.session_state.get("forget_round", 0) + 1
    if st.session_state.get("restore_checked"):
        return
    answer = _js(f"JSON.stringify([{storage}.getItem({json.dumps(SAVED_LOGIN_KEY)}) || '', "
                 f"{storage}.getItem({json.dumps(SAVED_PAGE_KEY)}) || ''])", key="restore-login")
    if answer is None:  # the browser hasn't answered yet; it reruns the page when it does
        st.caption("Restoring your sign-in…")
        st.stop()
    st.session_state.restore_checked = True
    try:
        saved, page = json.loads(answer)
    except (TypeError, ValueError):
        return
    if not saved:
        return
    st.session_state.refresh_token = saved
    st.session_state.restore_page = page or None
    try:
        if not api._refresh():
            raise api.SessionExpired("expired")
        st.session_state.user = None
        me = api._send("GET", "/api/v1/users/me", token=st.session_state.access_token)
        if not me.ok or me.json().get("role") not in config.STAFF_ROLES:
            raise api.SessionExpired("not staff")
        st.session_state.user = api._unescape(me.json())
        st.session_state.demo = False
        st.session_state.saved_login = st.session_state.refresh_token
    except api.ApiError:  # expired, revoked or unreachable: forget it and show the sign-in page
        clear_session()
        restore_login()
        return
    st.rerun()


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
