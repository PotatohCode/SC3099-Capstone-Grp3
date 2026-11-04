"""My account (every staff role): see who you're signed in as, fix your name
(PUT /users/me) and change your password (POST /users/me/password)."""
from __future__ import annotations

import streamlit as st

import api
import auth
import ui

PASSWORD_ERRORS = {
    "PASSWORD_INCORRECT": "Your current password is wrong. After 10 wrong tries the account is locked for a while.",
    "PASSWORD_UNCHANGED": "The new password must be different from the current one.",
    "ACCOUNT_LOCKED": "Too many wrong passwords: the account is locked for now. Try again later.",
}


def _name_form(user: dict) -> None:
    with st.form("my-name"):
        name = st.text_input("Name", value=user.get("full_name") or "", max_chars=200)
        if st.form_submit_button("Save name"):
            if not name.strip():
                st.warning("Your name can't be empty.")
            elif name.strip() == (user.get("full_name") or ""):
                st.info("Nothing changed.")
            else:
                updated = ui.safe(api.put, "/api/v1/users/me", {"full_name": name.strip()})
                if updated:
                    st.session_state.user = {**user, "full_name": updated.get("full_name", name.strip())}
                    ui.flash("Name saved.", "✅")
                    st.rerun()


def _password_form() -> None:
    with st.form("my-password", clear_on_submit=True):
        current = st.text_input("Current password", type="password")
        new = st.text_input("New password", type="password", help="At least 8 characters.")
        again = st.text_input("New password again", type="password")
        submitted = st.form_submit_button("Change password", type="primary")
    if not submitted:
        return
    if not current or not new:
        st.warning("Enter your current password and a new one.")
    elif len(new) < 8:
        st.warning("The new password needs at least 8 characters.")
    elif new != again:
        st.warning("The two new passwords don't match.")
    else:
        try:
            api.post("/api/v1/users/me/password", {"current_password": current, "new_password": new})
        except api.ApiError as err:
            if isinstance(err, api.SessionExpired) or err.code not in PASSWORD_ERRORS:
                ui.show_error(err)
            else:
                st.warning(PASSWORD_ERRORS[err.code], icon="⚠️")
        else:
            ui.flash("Password changed. You stay signed in here; other devices were signed out.", "🔑")
            st.rerun()


def render() -> None:
    ui.header("MY ACCOUNT", "My account", "Your name and password for the instructor portal.")
    user = auth.user()
    roles = {"ta": "TA", "instructor": "Instructor", "admin": "Admin"}
    ui.metric_row([
        ("Email", user.get("email") or "—", "Your sign-in email. An admin can't change it either."),
        ("Role", roles.get(user.get("role"), user.get("role") or "—"), None),
    ])
    left, right = st.columns(2)
    with left:
        st.subheader("Name", anchor=False)
        _name_form(user)
    with right:
        st.subheader("Password", anchor=False)
        _password_form()
