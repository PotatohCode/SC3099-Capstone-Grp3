import os
import io
import json

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


st.set_page_config(page_title="SAIV | Operations", page_icon="SAIV", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
ALLOWED_ROLES = {"ta", "instructor", "admin"}


def api_request(method, path, token, **kwargs):
    """Call the backend using the current dashboard session."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    return requests.request(
        method,
        f"{BACKEND_URL}{path}",
        headers=headers,
        timeout=10,
        **kwargs,
    )


def api_json(method, path, token, **kwargs):
    try:
        response = api_request(method, path, token, **kwargs)
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as exc:
        return None, str(exc)
    except ValueError:
        return None, "The backend returned an invalid JSON response."

def login(email, password):
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/v1/auth/login",
            json={"email": email, "password": password},
            timeout=10,
        )
    except requests.RequestException as exc:
        return None, f"Backend unavailable: {exc}"

    if response.status_code != 200:
        try:
            detail = response.json().get("detail", "Invalid email or password")
        except ValueError:
            detail = "Invalid email or password"
        return None, detail

    try:
        payload = response.json()
        user = payload.get("user", {})
        if payload.get("user") is None or not payload.get("access_token"):
            return None, "The backend returned an incomplete login response."
        return payload, None
    except ValueError:
        return None, "The backend returned an invalid login response."


def initialize_session():
    defaults = {
        "access_token": None,
        "current_user": None,
        "demo_mode": False,
        "login_error": None,
        "denied_role": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def render_login():
    st.markdown(
        """
        <div class="login-kicker">SECURE ATTENDANCE OPERATIONS</div>
        <h1 class="login-title">See attendance clearly.</h1>
        <p class="login-copy">Sign in with your staff account to monitor sessions, review risk, and export trusted records.</p>
        """,
        unsafe_allow_html=True,
    )
    with st.form("dashboard-login"):
        email = st.text_input("Staff email", placeholder="name@university.edu")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Open dashboard", use_container_width=True)

    st.divider()
    st.caption("Module 2 authentication is not available yet?")
    if st.button("Preview dashboard with sample data", use_container_width=True):
        st.session_state.access_token = "demo-preview"
        st.session_state.current_user = {
            "full_name": "Demo Instructor",
            "email": "demo@saiv.local",
            "role": "instructor",
        }
        st.session_state.demo_mode = True
        st.rerun()

    if submitted:
        if not email or not password:
            st.warning("Enter both your email and password.")
        else:
            payload, error = login(email, password)
            if error:
                st.session_state.login_error = error
            elif payload["user"].get("role") not in ALLOWED_ROLES:
                st.session_state.denied_role = payload["user"].get("role", "unknown")
                st.session_state.login_error = None
            else:
                st.session_state.access_token = payload["access_token"]
                st.session_state.current_user = payload["user"]
                st.session_state.login_error = None
                st.session_state.denied_role = None
                st.rerun()

    if st.session_state.login_error:
        st.error(st.session_state.login_error)
    if st.session_state.denied_role:
        st.error("Access denied. This dashboard is available only to TA, instructor, and admin accounts.")


def render_metric_cards(items):
    columns = st.columns(len(items))
    for column, (label, value, note) in zip(columns, items):
        with column:
            st.metric(label, value)
            st.caption(note)


def render_overview():
    user = st.session_state.current_user
    token = st.session_state.access_token
    first_name = user.get("full_name", user.get("email", "staff")).split()[0]
    st.markdown(f"<div class=\"eyebrow\">OPERATIONS OVERVIEW</div><h1>Good morning, {first_name}.</h1>", unsafe_allow_html=True)
    st.caption("Attendance intelligence for the courses and sessions in your access scope.")

    top_left, top_right = st.columns([5, 1])
    with top_right:
        if st.button("Refresh data", use_container_width=True):
            st.rerun()

    if st.session_state.demo_mode:
        st.warning("Preview mode: this dashboard is showing sample data, not live attendance records.")
        overview = {
            "today_checkins": 86,
            "active_sessions": 3,
            "average_attendance_rate": 0.91,
            "flagged_pending": 7,
            "trends": {
                "checkins_by_day": [
                    {"date": "2026-09-11", "count": 62},
                    {"date": "2026-09-12", "count": 74},
                    {"date": "2026-09-13", "count": 68},
                    {"date": "2026-09-14", "count": 81},
                    {"date": "2026-09-15", "count": 79},
                    {"date": "2026-09-16", "count": 88},
                    {"date": "2026-09-17", "count": 86},
                ],
                "attendance_rate_by_day": [
                    {"date": "2026-09-11", "rate": 0.84},
                    {"date": "2026-09-12", "rate": 0.87},
                    {"date": "2026-09-13", "rate": 0.86},
                    {"date": "2026-09-14", "rate": 0.89},
                    {"date": "2026-09-15", "rate": 0.90},
                    {"date": "2026-09-16", "rate": 0.92},
                    {"date": "2026-09-17", "rate": 0.91},
                ],
            },
        }
    else:
        try:
            response = api_request("GET", "/api/v1/stats/overview", token, params={"days": 7})
            response.raise_for_status()
            overview = response.json()
        except requests.RequestException as exc:
            st.error(f"Unable to load dashboard data: {exc}")
            st.info("Confirm that Module 2 is running at http://localhost:8000, then refresh this page.")
            return

    metrics = [
        ("Check-ins today", overview.get("today_checkins", overview.get("total_checkins_today", 0)), "Live attendance activity"),
        ("Active sessions", overview.get("active_sessions", 0), "Currently open windows"),
        ("Attendance rate", f"{overview.get('average_attendance_rate', overview.get('approval_rate', 0)):.1%}", "All-time approved attendance"),
        ("Needs review", overview.get("flagged_pending", overview.get("flagged_pending_review", 0)), "Flagged check-ins"),
    ]
    metric_columns = st.columns(4)
    for column, (label, value, note) in zip(metric_columns, metrics):
        with column:
            st.metric(label, value)
            st.caption(note)

    trends = overview.get("trends", {})
    chart_left, chart_right = st.columns([3, 2])
    with chart_left:
        checkins = pd.DataFrame(trends.get("checkins_by_day", []))
        st.subheader("Check-in activity")
        if checkins.empty:
            st.info("No trend data is available yet.")
        else:
            checkins["date"] = pd.to_datetime(checkins["date"])
            st.plotly_chart(
                px.area(checkins, x="date", y="count", markers=True, color_discrete_sequence=["#0f766e"]),
                use_container_width=True,
                config={"displayModeBar": False},
            )
    with chart_right:
        rates = pd.DataFrame(trends.get("attendance_rate_by_day", []))
        st.subheader("Attendance trend")
        if rates.empty:
            st.info("No attendance trend is available yet.")
        else:
            rates["date"] = pd.to_datetime(rates["date"])
            rates["rate"] = rates["rate"] * 100
            st.plotly_chart(
                px.line(rates, x="date", y="rate", markers=True, color_discrete_sequence=["#d97706"]),
                use_container_width=True,
                config={"displayModeBar": False},
            )


def render_sessions(token):
    st.markdown('<div class="eyebrow">SESSION CONTROL</div><h1>Sessions</h1>', unsafe_allow_html=True)
    data, error = api_json("GET", "/api/v1/sessions", token, params={"limit": 100})
    if error:
        st.error(f"Unable to load sessions: {error}")
        return
    rows = data.get("items", data if isinstance(data, list) else [])
    if not rows:
        st.info("No sessions are available in your access scope.")
        return
    frame = pd.DataFrame(rows)
    columns = [name for name in ["id", "session_id", "name", "course_code", "scheduled_start", "status"] if name in frame]
    st.dataframe(frame[columns] if columns else frame, use_container_width=True, hide_index=True)
    choices = {str(row.get("name", row.get("session_id", row.get("id")))): row.get("session_id", row.get("id")) for row in rows}
    selected = st.selectbox("Inspect a session", ["Select a session"] + list(choices))
    if selected == "Select a session":
        return
    details, detail_error = api_json("GET", f"/api/v1/stats/sessions/{choices[selected]}", token)
    if detail_error:
        st.error(f"Unable to load session details: {detail_error}")
        return
    render_metric_cards([
        ("Enrolled", details.get("total_enrolled", 0), "Students in course"),
        ("Checked in", details.get("checked_in", details.get("checked_in_count", 0)), "Raw check-in count"),
        ("Attendance", f"{details.get('attendance_rate', 0):.1%}", "Rejected attempts excluded"),
        ("Flagged", details.get("flagged_count", 0), "Requires review"),
    ])
    breakdown = details.get("by_status", {})
    if breakdown:
        chart = pd.DataFrame({"status": list(breakdown), "count": list(breakdown.values())})
        st.plotly_chart(px.bar(chart, x="status", y="count", color="status"), use_container_width=True, config={"displayModeBar": False})


def render_checkins(token):
    st.markdown('<div class="eyebrow">REVIEW QUEUE</div><h1>Check-ins</h1>', unsafe_allow_html=True)
    status = st.selectbox("Status filter", ["All", "pending", "flagged", "approved", "rejected", "appealed"])
    params = {"limit": 100}
    if status != "All":
        params["status"] = status
    data, error = api_json("GET", "/api/v1/checkins", token, params=params)
    if error:
        st.error(f"Unable to load check-ins: {error}")
        return
    rows = data.get("items", data if isinstance(data, list) else [])
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("Review actions remain enforced by the backend role permissions.")


def render_courses(token):
    st.markdown('<div class="eyebrow">ANALYTICS</div><h1>Courses</h1>', unsafe_allow_html=True)
    data, error = api_json("GET", "/api/v1/courses", token, params={"limit": 100})
    if error:
        st.error(f"Unable to load courses: {error}")
        return
    rows = data.get("items", data if isinstance(data, list) else [])
    if not rows:
        st.info("No courses are available in your access scope.")
        return
    choices = {f"{row.get('course_code', '')} {row.get('course_name', '')}".strip(): row.get("id", row.get("course_id")) for row in rows}
    selected = st.selectbox("Select a course", list(choices))
    details, detail_error = api_json("GET", f"/api/v1/stats/courses/{choices[selected]}", token)
    if detail_error:
        st.error(f"Unable to load course analytics: {detail_error}")
        return
    render_metric_cards([
        ("Sessions", details.get("total_sessions", 0), "In selected course"),
        ("Enrolled", details.get("total_enrolled", 0), "Current enrollment"),
        ("Attendance", f"{details.get('overall_attendance_rate', details.get('average_attendance_rate', 0)):.1%}", "Overall rate"),
        ("Flagged", details.get("flagged_checkins", 0), "Check-ins for review"),
    ])
    st.subheader("Low-attendance alerts")
    alerts = pd.DataFrame(details.get("low_attendance_alerts", []))
    st.dataframe(alerts if not alerts.empty else pd.DataFrame({"status": ["No alerts"]}), use_container_width=True, hide_index=True)
    students = pd.DataFrame(details.get("student_attendance", []))
    if not students.empty:
        st.subheader("Student attendance")
        st.dataframe(students, use_container_width=True, hide_index=True)


def render_students(token):
    st.markdown('<div class="eyebrow">STUDENT INSIGHTS</div><h1>Students</h1>', unsafe_allow_html=True)
    student_id = st.text_input("Student ID", placeholder="Enter a student UUID")
    if not student_id:
        st.info("Enter a student ID to view scoped attendance details.")
        return
    details, error = api_json("GET", f"/api/v1/stats/students/{student_id}", token)
    if error:
        st.error(f"Unable to load student details: {error}")
        return
    render_metric_cards([
        ("Courses", details.get("total_enrolled_courses", 0), "Enrolled courses"),
        ("Sessions attended", details.get("attended_sessions", 0), f"of {details.get('total_sessions', 0)} sessions"),
        ("Attendance", f"{details.get('attendance_rate', 0):.1%}", "Across accessible courses"),
        ("Student", details.get("student_name", "Unknown"), details.get("student_email", "")),
    ])
    st.dataframe(pd.DataFrame(details.get("recent_checkins", details.get("recent_sessions", []))), use_container_width=True, hide_index=True)


def render_exports(token):
    st.markdown('<div class="eyebrow">REPORTING</div><h1>Exports</h1>', unsafe_allow_html=True)
    kind = st.radio("Export scope", ["Course", "Session"], horizontal=True)
    resource_id = st.text_input(f"{kind} ID")
    format_name = st.selectbox("Format", ["csv", "json"])
    if not (st.button("Prepare export", type="primary") and resource_id):
        return
    try:
        response = api_request("GET", f"/api/v1/export/{kind.lower()}/{resource_id}", token, params={"format": format_name})
        response.raise_for_status()
        filename = f"{kind.lower()}-{resource_id}.{format_name}"
        if format_name == "json":
            body = response.json()
            st.download_button("Download JSON", data=json.dumps(body, indent=2), file_name=filename, mime="application/json")
            st.json(body)
        else:
            st.download_button("Download CSV", data=response.content, file_name=filename, mime="text/csv")
            st.dataframe(pd.read_csv(io.BytesIO(response.content)), use_container_width=True, hide_index=True)
    except (requests.RequestException, ValueError) as exc:
        st.error(f"Unable to prepare export: {exc}")


def render_audit(token):
    st.markdown('<div class="eyebrow">COMPLIANCE</div><h1>Audit activity</h1>', unsafe_allow_html=True)
    days = st.slider("Summary period", 1, 365, 30)
    summary, error = api_json("GET", "/api/v1/audit/summary", token, params={"days": days})
    if error:
        st.error(f"Unable to load audit summary: {error}")
        return
    render_metric_cards([
        ("Total logs", summary.get("total_logs", 0), f"Last {days} days"),
        ("Successful", summary.get("success_count", 0), "Recorded events"),
        ("Failed", summary.get("failed_count", 0), "Requires attention"),
    ])
    logs, logs_error = api_json("GET", "/api/v1/audit/", token, params={"limit": 100})
    if logs_error:
        st.error(f"Unable to load audit activity: {logs_error}")
        return
    st.dataframe(pd.DataFrame(logs.get("items", [])), use_container_width=True, hide_index=True)


def render_metrics():
    st.markdown('<div class="eyebrow">SYSTEM HEALTH</div><h1>Metrics</h1>', unsafe_allow_html=True)
    st.caption(f"Prometheus endpoint: {PROMETHEUS_URL}")
    try:
        response = requests.get(f"{BACKEND_URL}/metrics", timeout=10)
        response.raise_for_status()
        lines = [line for line in response.text.splitlines() if line and not line.startswith("#")]
        st.metric("Exposed metric samples", len(lines))
        st.code("\n".join(lines[:200]), language="text")
        st.link_button("Open Grafana", "http://localhost:3001")
    except requests.RequestException as exc:
        st.error(f"Metrics endpoint unavailable: {exc}")


def render_dashboard():
    user = st.session_state.current_user
    token = st.session_state.access_token
    role = user.get("role")
    navigation = ["Overview", "Sessions", "Check-ins", "Metrics"]
    if role in {"instructor", "admin"}:
        navigation.extend(["Courses", "Students", "Exports"])
    elif role == "ta":
        navigation.append("Exports")
    if role == "admin":
        navigation.append("Audit")
    with st.sidebar:
        st.markdown("## SAIV")
        st.caption("Attendance operations")
        st.divider()
        page = st.radio(
            "Navigate",
            navigation,
            label_visibility="collapsed",
        )
        st.divider()
        st.write(f"**{user.get('full_name', user.get('email', 'Staff'))}**")
        st.caption(user.get("role", "staff").title())
        if st.button("Sign out", use_container_width=True):
            for key in ("access_token", "current_user", "demo_mode"):
                st.session_state[key] = None
            st.rerun()
        st.divider()
        st.caption("Backend")
        st.code(BACKEND_URL, language=None)

    pages = {
        "Overview": lambda: render_overview(),
        "Sessions": lambda: render_sessions(token),
        "Check-ins": lambda: render_checkins(token),
        "Courses": lambda: render_courses(token),
        "Students": lambda: render_students(token),
        "Exports": lambda: render_exports(token),
        "Audit": lambda: render_audit(token),
        "Metrics": render_metrics,
    }
    pages[page]()


initialize_session()
st.markdown(
    """
    <style>
    :root { --ink: #173042; --muted: #61727a; --teal: #0f766e; --paper: #f6f7f2; }
    .stApp { background: var(--paper); color: var(--ink); }
    .block-container { max-width: 1240px; padding-top: 3rem; }
    h1 { letter-spacing: 0; color: var(--ink); font-weight: 700; }
    h2, h3 { color: var(--ink); }
    .eyebrow, .login-kicker { color: var(--teal); font-size: .76rem; font-weight: 800; letter-spacing: .13em; }
    .login-title { font-size: 3rem; margin-bottom: .25rem; }
    .login-copy { color: var(--muted); max-width: 34rem; font-size: 1.05rem; margin-bottom: 2rem; }
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-testid="stDateInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stSelectbox"] div[data-baseweb="select"],
    [data-testid="stMultiSelect"] div[data-baseweb="select"] {
        background: #ffffff !important;
        color: var(--ink) !important;
        border-color: #aab8b8 !important;
    }
    [data-testid="stTextInput"] input::placeholder,
    [data-testid="stNumberInput"] input::placeholder,
    [data-testid="stTextArea"] textarea::placeholder {
        color: #718083 !important;
        opacity: 1;
    }
    [data-testid="stTextInput"] label,
    [data-testid="stNumberInput"] label,
    [data-testid="stSelectbox"] label,
    [data-testid="stRadio"] label,
    [data-testid="stSlider"] label {
        color: var(--ink) !important;
    }
    [data-testid="stButton"] button,
    [data-testid="stFormSubmitButton"] button {
        color: #ffffff !important;
        background: var(--teal) !important;
        border: 1px solid var(--teal) !important;
    }
    [data-testid="stSidebar"] [data-testid="stTextInput"] input,
    [data-testid="stSidebar"] [data-testid="stSelectbox"] div[data-baseweb="select"] {
        color: var(--ink) !important;
        background: #ffffff !important;
    }
    [data-testid="stSidebar"] pre,
    [data-testid="stSidebar"] pre code,
    [data-testid="stSidebar"] [data-testid="stCodeBlock"] {
        background: #102532 !important;
        color: #d9f4ee !important;
        border: 1px solid #48616b !important;
    }
    [data-testid="stSidebar"] pre code span {
        color: #d9f4ee !important;
    }
    [data-testid="stMetric"] { background: white; border: 1px solid #e2e8e5; border-radius: 8px; padding: 1rem; }
    [data-testid="stSidebar"] { background: #173042; }
    [data-testid="stSidebar"] * { color: #f4f7f4; }
    </style>
    """,
    unsafe_allow_html=True,
)

if st.session_state.access_token and st.session_state.current_user:
    render_dashboard()
else:
    render_login()
