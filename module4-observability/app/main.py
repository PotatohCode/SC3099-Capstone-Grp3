"""SAIV instructor portal (Module 4). Entry point: shows the sign-in page,
or the pages the signed-in role may use.

Run: streamlit run app/main.py"""
import streamlit as st

import auth
import ui
from views import (account, accounts, audit, checkins, courses, exports_page, manage, overview, review, sessions,
                   students, system)

st.set_page_config(page_title="SAIV · Instructor portal", page_icon="🎓", layout="wide")

st.markdown("""
<style>
  .eyebrow { color: #0f766e; font-size: .75rem; font-weight: 800; letter-spacing: .13em; margin-bottom: -.5rem; }
  [data-testid="stMetric"] { background: var(--secondary-background-color); }
  /* The pick-a-spot map can report a wrong frame height on first draw (blank gap below it). */
  iframe[title="streamlit_folium.st_folium"] { height: 330px !important; }
  [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { opacity: .8; }
  /* Tables' own "Download as CSV" skips the formula-injection guard and the audit log;
     downloads go through the Exports page / session export instead. */
  [data-testid="stElementToolbarButton"]:has(button[aria-label="Download as CSV"]) { display: none !important; }
</style>
""", unsafe_allow_html=True)

auth.init_session()

if not auth.is_signed_in():
    auth.restore_login()  # a browser refresh: sign back in from the tab's saved login
    st.navigation([st.Page(auth.login_page, title="Sign in", icon="🔐")], position="hidden").run()
    st.stop()

PAGES = {
    "today": st.Page(overview.render, title="Today", icon="🏠", url_path="today", default=True),
    "review": st.Page(review.render, title="Review queue", icon="🚩", url_path="review"),
    "sessions": st.Page(sessions.render, title="Sessions", icon="🗓️", url_path="sessions"),
    "checkins": st.Page(checkins.render, title="Check-ins", icon="🔎", url_path="checkins"),
    "courses": st.Page(courses.render, title="Courses", icon="📊", url_path="courses"),
    "students": st.Page(students.render, title="Students", icon="🎓", url_path="students"),
    "exports": st.Page(exports_page.render, title="Exports", icon="⬇️", url_path="exports"),
    "accounts": st.Page(accounts.render, title="Accounts", icon="👥", url_path="accounts"),
    "manage": st.Page(manage.render, title="Users & courses", icon="🛠️", url_path="manage"),
    "audit": st.Page(audit.render, title="Audit log", icon="🧾", url_path="audit"),
    "system": st.Page(system.render, title="System health", icon="🩺", url_path="system"),
    "account": st.Page(account.render, title="My account", icon="🔑", url_path="account"),
}
st.session_state.pages = PAGES

menu = {"Attendance": [PAGES["today"], PAGES["review"], PAGES["sessions"], PAGES["checkins"]]}
analytics = [PAGES[k] for k, allowed in (("courses", auth.can("course_analytics")),
                                         ("students", auth.can("student_analytics"))) if allowed]
menu["Analytics"] = analytics + [PAGES["exports"]]
admin = [PAGES[k] for k, allowed in (("accounts", auth.can("manage_accounts")), ("manage", auth.can("manage")),
                                     ("audit", auth.can("audit")), ("system", auth.can("system"))) if allowed]
if admin:
    menu["Administration"] = admin
menu["You"] = [PAGES["account"]]

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

page = st.navigation(menu)
current = next((key for key, p in PAGES.items() if p.url_path == page.url_path), "today")
# After a browser refresh, go back to the page that was open (the URL is lost while
# the saved login is read back), if this role can open it.
restore_page = st.session_state.pop("restore_page", None)
if restore_page and restore_page != current and any(PAGES.get(restore_page) is p for ps in menu.values() for p in ps):
    st.switch_page(PAGES[restore_page])
auth.remember_login(current)

try:
    page.run()
except Exception as err:  # last-resort guard so one page bug never blanks the app
    from api import ApiError
    if isinstance(err, ApiError):
        ui.show_error(err)
    else:
        raise
