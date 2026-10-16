"""Accounts: create accounts (one or by CSV) and manage course rosters.

Who may create what (team rule): admin -> any role, instructor -> student/ta.
- admin uses POST /admin/users/bulk (the backend allows admins only);
- instructor uses POST /auth/register. That endpoint is public by course
  design ("ignore security restrictions about the roles during
  registration"), so the student/ta limit for instructors is applied here.
Students and TAs are linked to a course through enrolments (a TA's course
access comes from being enrolled in it)."""
from __future__ import annotations

import io
import re

import pandas as pd
import streamlit as st

import api
import auth
import ui

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CSV_COLUMNS = ["email", "full_name", "role", "password"]
ADMIN_BATCH = 50  # keeps each request well under the 30 s timeout (bcrypt ~0.1 s per account)


def _allowed_roles() -> list[str]:
    return auth.CREATABLE_ROLES.get(auth.role(), [])


def _validate(email: str, name: str, role: str, password: str) -> str | None:
    if not EMAIL_RE.match(email or ""):
        return "invalid email"
    if not (name or "").strip():
        return "full name is missing"
    if role not in _allowed_roles():
        return f"you can't create '{role}' accounts"
    if len(password or "") < 8:
        return "password must be at least 8 characters"
    return None


def _create(users: list[dict], progress=None) -> tuple[list[dict], list[dict]]:
    """Creates accounts; returns (created users, [{email, error}])."""
    created, errors = [], []
    if auth.role() == "admin":
        for start in range(0, len(users), ADMIN_BATCH):
            batch = users[start:start + ADMIN_BATCH]
            try:
                result = api.post("/api/v1/admin/users/bulk", {"users": batch})
                created += result.get("users", [])
                errors += result.get("errors", [])
            except api.ApiError as err:
                if isinstance(err, api.SessionExpired):
                    raise
                errors += [{"email": u["email"], "error": str(err)} for u in batch]
            if progress:
                progress.progress(min((start + len(batch)) / len(users), 1.0))
    else:
        for index, item in enumerate(users):
            try:
                created.append(api.post("/api/v1/auth/register", item))
            except api.ApiError as err:
                if isinstance(err, api.SessionExpired):
                    raise
                errors.append({"email": item["email"], "error": str(err)})
            if progress:
                progress.progress((index + 1) / len(users))
    return created, errors


def _enrol(course_id: str, emails: list[str]) -> dict | None:
    if not emails:
        return None
    return ui.safe(api.post, "/api/v1/enrollments/bulk", {"course_id": course_id, "student_emails": emails})


def _course_picker(key: str, label: str = "Enrol in course (optional)") -> dict | None:
    courses = ui.safe(auth.creatable_courses, default=[])
    return ui.pick(label, courses, ui.course_label, key=key, placeholder="Don't enrol")


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def _single() -> None:
    with st.form("create-account", clear_on_submit=True):
        left, right = st.columns(2)
        email = left.text_input("Email", placeholder="student@e.ntu.edu.sg")
        name = right.text_input("Full name")
        role = left.selectbox("Role", _allowed_roles(), format_func=lambda r: "TA" if r == "ta" else r.title())
        course = _course_picker("single-course")
        password = left.text_input("Temporary password", type="password", help="At least 8 characters.")
        confirm = right.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create account", type="primary")
    if not submitted:
        return
    email = email.strip().lower()
    problem = _validate(email, name, role, password) or (None if password == confirm else "passwords don't match")
    if problem:
        st.warning(f"Can't create the account: {problem}.")
        return
    try:
        created, errors = _create([{"email": email, "full_name": name.strip(), "role": role, "password": password}])
    except api.ApiError as err:
        ui.show_error(err)
        return
    if errors:
        st.error(f"{email}: {errors[0]['error']}")
        return
    st.success(f"Created {role} account for {email}. Share the temporary password with them privately.")
    if course and role in {"student", "ta"}:
        result = _enrol(course["id"], [email])
        if result and result.get("enrolled"):
            st.success(f"Enrolled in {ui.course_label(course)}.")


def _csv_import() -> None:
    st.markdown("Upload a CSV with the columns **email, full_name, role, password**. "
                f"Allowed roles for you: {', '.join(_allowed_roles())}.")
    template = pd.DataFrame([["student1@e.ntu.edu.sg", "Student One", "student", "ChangeMe123"]],
                            columns=CSV_COLUMNS).to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Download template", template, "saiv-accounts-template.csv", "text/csv")
    upload = st.file_uploader("Accounts CSV", type=["csv"], key="accounts-csv")
    if not upload:
        return
    try:
        frame = pd.read_csv(io.BytesIO(upload.getvalue()), dtype=str, keep_default_na=False)
    except (ValueError, UnicodeDecodeError) as err:
        st.error(f"Couldn't read the file as CSV: {err}")
        return
    frame.columns = [c.strip().lower() for c in frame.columns]
    missing = [c for c in CSV_COLUMNS if c not in frame.columns]
    if missing:
        st.error(f"Missing column(s): {', '.join(missing)}.")
        return
    if len(frame) > 1000:
        st.error("Please import at most 1,000 accounts at a time.")
        return
    frame = frame[CSV_COLUMNS].apply(lambda col: col.str.strip())
    frame["email"] = frame["email"].str.lower()
    frame["role"] = frame["role"].str.lower().replace("", "student")
    frame["problem"] = [_validate(r.email, r.full_name, r.role, r.password) or "" for r in frame.itertuples()]
    duplicated = frame["email"].duplicated(keep="first")
    frame.loc[duplicated & (frame["problem"] == ""), "problem"] = "duplicate email in file"

    valid = frame[frame["problem"] == ""]
    st.write(f"**{len(valid)}** ready to create, **{len(frame) - len(valid)}** with problems.")
    st.dataframe(frame.drop(columns=["password"]).rename(columns={"problem": "Problem"}),
                 hide_index=True, use_container_width=True)
    course = _course_picker("csv-course", "Enrol the new students/TAs in course (optional)")
    if not st.button(f"Create {len(valid)} account(s)", type="primary", disabled=valid.empty):
        return
    progress = st.progress(0.0)
    users = valid[["email", "full_name", "role", "password"]].to_dict("records")
    try:
        created, errors = _create(users, progress)
    except api.ApiError as err:
        ui.show_error(err)
        return
    st.success(f"Created {len(created)} account(s).")
    if errors:
        st.warning(f"{len(errors)} couldn't be created:")
        st.dataframe(pd.DataFrame(errors), hide_index=True, use_container_width=True)
    if course:
        emails = [u["email"] for u in created if u.get("role") in {"student", "ta"}]
        result = _enrol(course["id"], emails)
        if result:
            st.success(f"Enrolled {result.get('enrolled', 0)} in {ui.course_label(course)}.")


@st.dialog("Remove from course")
def _confirm_remove(row: dict, course: dict) -> None:
    st.write(f"Remove **{row['student_name']}** ({row['student_email']}) from **{ui.course_label(course)}**?")
    st.caption("Their past check-ins are kept. You can enrol them again later.")
    left, right = st.columns(2)
    if left.button("Remove", type="primary", use_container_width=True):
        if ui.safe(api.delete, f"/api/v1/enrollments/{row['id']}", default=False) is not False:
            ui.flash("Removed from course.", "✅")
            st.rerun()
    if right.button("Cancel", use_container_width=True):
        st.rerun()


def _roster() -> None:
    courses = ui.safe(auth.creatable_courses, default=[])
    course = ui.pick("Course", courses, ui.course_label, key="roster-course")
    if not course:
        return
    with st.form("enrol-existing", clear_on_submit=True):
        emails_text = st.text_area("Enrol existing accounts (one email per line, students or TAs)")
        if st.form_submit_button("Enrol"):
            emails = sorted({e.strip().lower() for e in re.split(r"[\s,;]+", emails_text) if e.strip()})
            bad = [e for e in emails if not EMAIL_RE.match(e)]
            if bad:
                st.warning(f"Not valid email(s): {', '.join(bad)}")
            else:
                result = _enrol(course["id"], emails)
                if result:
                    st.success(f"Enrolled {result.get('enrolled', 0)}, already enrolled {result.get('already_enrolled', 0)}, "
                               f"no account found {result.get('not_found', 0)}.")
                    missing = [d["email"] for d in result.get("details", []) if d["status"] == "not_found"]
                    if missing:
                        st.caption("No account for: " + ", ".join(missing) + ". Create them in the tabs above first.")

    roster = ui.safe(api.get, f"/api/v1/enrollments/course/{course['id']}") or {}
    rows = roster.get("students", [])
    st.markdown(f"**{len(rows)} enrolled** (assigned TAs are listed here too)")
    if not rows:
        return
    frame = pd.DataFrame([{
        "Name": r["student_name"], "Email": r["student_email"], "Enrolled": r.get("enrolled_at"),
        "Face enrolled": r.get("face_enrolled"),
    } for r in rows])
    ui.local_datetime_column(frame, "Enrolled")
    event = st.dataframe(frame, hide_index=True, use_container_width=True, on_select="rerun",
                         selection_mode="single-row", key=f"roster-{course['id']}",
                         column_config={"Enrolled": st.column_config.DatetimeColumn(format="D MMM YYYY"),
                                        "Face enrolled": st.column_config.CheckboxColumn()})
    picked = event.selection.rows if event and event.selection else []
    if picked and st.button(f"Remove {rows[picked[0]]['student_name']} from course"):
        _confirm_remove(rows[picked[0]], course)


def render() -> None:
    who = "any role" if auth.role() == "admin" else "student and TA"
    ui.header("ACCOUNTS", "Accounts", f"Create {who} accounts and manage who is enrolled in your courses.")
    single, bulk, roster = st.tabs(["Create account", "Import CSV", "Course roster"])
    with single:
        _single()
    with bulk:
        _csv_import()
    with roster:
        _roster()
