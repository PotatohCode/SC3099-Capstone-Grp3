"""SAIV instructor portal (Module 4). Entry point: shows the sign-in page,
or the pages the signed-in role may use.

Run: streamlit run app/main.py"""
import streamlit as st

import auth
import ui
from views import accounts, audit, courses, exports_page, overview, review, sessions, students, system

st.set_page_config(page_title="SAIV · Instructor portal", page_icon="🎓", layout="wide")

st.markdown("""
<style>
  .eyebrow { color: #0f766e; font-size: .75rem; font-weight: 800; letter-spacing: .13em; margin-bottom: -.5rem; }
  [data-testid="stMetric"] { background: var(--secondary-background-color); }
  [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { opacity: .8; }
</style>
""", unsafe_allow_html=True)

auth.init_session()

if not auth.is_signed_in():
    st.navigation([st.Page(auth.login_page, title="Sign in", icon="🔐")], position="hidden").run()
    st.stop()

PAGES = {
    "today": st.Page(overview.render, title="Today", icon="🏠", url_path="today", default=True),
    "review": st.Page(review.render, title="Review queue", icon="🚩", url_path="review"),
    "sessions": st.Page(sessions.render, title="Sessions", icon="🗓️", url_path="sessions"),
    "courses": st.Page(courses.render, title="Courses", icon="📊", url_path="courses"),
    "students": st.Page(students.render, title="Students", icon="🎓", url_path="students"),
    "exports": st.Page(exports_page.render, title="Exports", icon="⬇️", url_path="exports"),
    "accounts": st.Page(accounts.render, title="Accounts", icon="👥", url_path="accounts"),
    "audit": st.Page(audit.render, title="Audit log", icon="🧾", url_path="audit"),
    "system": st.Page(system.render, title="System health", icon="🩺", url_path="system"),
}
st.session_state.pages = PAGES

menu = {"Attendance": [PAGES["today"], PAGES["review"], PAGES["sessions"]]}
analytics = [PAGES[k] for k, allowed in (("courses", auth.can("course_analytics")),
                                         ("students", auth.can("student_analytics"))) if allowed]
menu["Analytics"] = analytics + [PAGES["exports"]]
admin = [PAGES[k] for k, allowed in (("accounts", auth.can("manage_accounts")), ("audit", auth.can("audit")),
                                     ("system", auth.can("system"))) if allowed]
if admin:
    menu["Administration"] = admin

with st.sidebar:
    user = auth.user()
    st.markdown("### 🎓 SAIV")
    st.caption("Secure attendance · instructor portal")
    st.divider()
    st.markdown(f"**{user.get('full_name', 'Staff')}**")
    st.caption(f"{user.get('role', '').upper()} · {user.get('email', '')}")
    st.session_state.live_updates = st.toggle("Live updates", value=st.session_state.live_updates,
                                              help="Refresh live numbers every 30 seconds.")
    if st.button("Sign out", use_container_width=True):
        auth.sign_out()
        st.rerun()

try:
    st.navigation(menu).run()
except Exception as err:  # last-resort guard so one page bug never blanks the app
    from api import ApiError
    if isinstance(err, ApiError):
        ui.show_error(err)
    else:
        raise
