"""Manage (admin): courses, user accounts and devices. Every call here is
admin-only in the backend (POST/PUT/DELETE /courses, PATCH/DELETE /users/{id},
/admin/users/{id}/activate|deactivate, GET /devices/, PATCH/DELETE /devices/{id})."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import api
import auth
import ui
from views.sessions import course_location, forget_venues, location_picker

ROLE_LABELS = {"student": "Student", "ta": "TA", "instructor": "Instructor", "admin": "Admin"}


def _reload_courses() -> None:
    """Course changes affect who manages what, and the Saved venue list."""
    st.session_state.pop("scope_course_ids", None)
    forget_venues()


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

def _instructors() -> list[dict]:
    return ui.safe(api.get_all, "/api/v1/users/", role="instructor", is_active=True, default=[])


def _instructor_picker(label: str, key: str, current: str | None = None) -> str | None:
    people = {u["id"]: u for u in _instructors()}
    options = [None] + list(people)
    index = options.index(current) if current in options else 0
    return st.selectbox(label, options, index=index, key=key,
                        format_func=lambda uid: "Nobody yet (any instructor may use it)" if uid is None
                        else f"{people[uid]['full_name']} · {people[uid]['email']}")


def _location_fields(key: str, course: dict | None = None) -> dict | None:
    """The course's default location: none, or a pin on the map. Returns the
    venue fields to send, or None while the pin is missing / outside Singapore."""
    saved = course_location(course) if course else None
    mode = st.radio("Default location", ["none", "set"], index=1 if saved else 0, key=f"cloc-mode-{key}",
                    horizontal=True, format_func=lambda m: "No default location" if m == "none" else "Set a location",
                    help="Sessions use the course's location unless they set their own.")
    if mode == "none":
        st.caption("Each session will then need its own location, or students could check in from anywhere.")
        return {"venue_name": None, "venue_latitude": None, "venue_longitude": None}
    if course:
        _session_location_copy(key, course)
    lat, lon, radius, venue = location_picker(f"course-{key}", saved, (course or {}).get("venue_name") or "")
    if lat is None or lon is None:
        st.info("Click the map where the course meets, or enter the latitude and longitude.")
        return None
    if not ui.in_singapore(lat, lon):
        st.error("Those coordinates are outside Singapore, so nobody could check in. Check the numbers.")
        return None
    return {"venue_name": venue.strip() or None, "venue_latitude": lat, "venue_longitude": lon,
            "geofence_radius_meters": float(radius)}


def _session_location_copy(key: str, course: dict) -> None:
    """'Use a session's location': copies a location a session of this course
    used into the boxes, to make it the course's default."""
    sessions = ui.safe(api.get_all, "/api/v1/sessions/", course_id=course["id"], default=[])
    places = {}
    for s in sessions:
        if s.get("venue_latitude") is not None and s.get("venue_longitude") is not None:
            label = f"{s.get('venue_name') or 'Unnamed'} · {s['venue_latitude']:.4f}, {s['venue_longitude']:.4f} " \
                    f"(from “{s.get('name')}”)"
            places.setdefault(label, s)
    if not places:
        return
    picker = f"loc-from-session-{key}"

    def fill() -> None:
        s = places.get(st.session_state.get(picker))
        if s:
            box = f"course-{key}"
            st.session_state[f"loc-lat-{box}"] = s["venue_latitude"]
            st.session_state[f"loc-lon-{box}"] = s["venue_longitude"]
            st.session_state[f"loc-r-{box}"] = int(s.get("geofence_radius_meters") or 100)
            st.session_state[f"loc-name-{box}"] = s.get("venue_name") or ""
            st.session_state[f"loc-saved-{box}"] = None

    st.selectbox("Use a session's location", list(places), index=None, key=picker, on_change=fill,
                 placeholder="Copy a location one of this course's sessions used (optional)")


def _create_course() -> None:
    left, right = st.columns(2)
    code = left.text_input("Course code", max_chars=20, placeholder="SC3099", key="nc-code")
    name = right.text_input("Course name", max_chars=200, placeholder="Capstone Project", key="nc-name")
    semester = left.text_input("Semester", max_chars=20, placeholder="AY2026-27 S1", key="nc-sem")
    with right:
        instructor = _instructor_picker("Instructor", "nc-instructor")
    description = st.text_area("Description (optional)", max_chars=1000, key="nc-desc")
    a, b = st.columns(2)
    face = a.toggle("Require face recognition", value=False, key="nc-face")
    device = b.toggle("Require a registered device", value=True, key="nc-device")
    location = _location_fields("new")
    if not st.button("Create course", type="primary", disabled=location is None, key="nc-create"):
        return
    code = code.strip().upper()
    if not code or not name.strip() or not semester.strip():
        st.warning("Enter the course code, name and semester.")
        return
    body = {"code": code, "name": name.strip(), "semester": semester.strip(), "instructor_id": instructor,
            "description": description.strip() or None, "require_face_recognition": face,
            "require_device_binding": device, **{k: v for k, v in location.items() if v is not None}}
    created = ui.safe(api.post, "/api/v1/courses/", body)
    if created:
        # Empty the form (its boxes and its map) for the next course.
        for k in [k for k in st.session_state if str(k).startswith("nc-") or str(k).endswith("-new")
                  or "-course-new" in str(k)]:
            del st.session_state[k]
        _reload_courses()
        ui.flash(f"Course {created['code']} created.", "✅")
        st.rerun()


@st.dialog("Confirm")
def _confirm_archive(course: dict, archive: bool) -> None:
    st.write(f"{'Archive' if archive else 'Restore'} **{ui.md(ui.course_label(course))}**?")
    st.caption("It disappears from course lists and session forms. Its sessions, check-ins and enrolments "
               "are kept, and you can restore it later." if archive else
               "It shows in course lists and session forms again.")
    left, right = st.columns(2)
    if left.button("Archive" if archive else "Restore", type="primary", use_container_width=True):
        call = (lambda: api.delete(f"/api/v1/courses/{course['id']}")) if archive else \
            (lambda: api.put(f"/api/v1/courses/{course['id']}", {"is_active": True}))
        if ui.safe(call, default=False) is not False:
            st.session_state.pop("manage-course", None)
            _reload_courses()
            ui.flash(f"Course {'archived' if archive else 'restored'}.", "🗄️" if archive else "✅")
            st.rerun()
    if right.button("Cancel", use_container_width=True):
        st.rerun()


def _edit_course(course: dict) -> None:
    key = course["id"]
    st.markdown(f"**Edit {ui.md(ui.course_label(course))}**")
    left, right = st.columns(2)
    name = left.text_input("Course name", value=course.get("name") or "", max_chars=200, key=f"ec-name-{key}")
    semester = right.text_input("Semester", value=course.get("semester") or "", max_chars=20, key=f"ec-sem-{key}")
    with left:
        instructor = _instructor_picker("Instructor", f"ec-instructor-{key}", course.get("instructor_id"))
    description = right.text_area("Description", value=course.get("description") or "", max_chars=1000,
                                  key=f"ec-desc-{key}")
    a, b = st.columns(2)
    face = a.toggle("Require face recognition", value=bool(course.get("require_face_recognition")),
                    key=f"ec-face-{key}")
    device = b.toggle("Require a registered device", value=bool(course.get("require_device_binding")),
                      key=f"ec-device-{key}")
    location = _location_fields(key, course)
    save, archive = st.columns([1, 1])
    if save.button("Save changes", type="primary", disabled=location is None, key=f"ec-save-{key}",
                   use_container_width=True):
        if not name.strip() or not semester.strip():
            st.warning("The course name and semester can't be empty.")
            return
        wanted = {"name": name.strip(), "semester": semester.strip(), "instructor_id": instructor,
                  "description": description.strip() or None, "require_face_recognition": face,
                  "require_device_binding": device, **location}
        changes = {k: v for k, v in wanted.items() if course.get(k) != v}
        if not changes:
            st.info("Nothing changed.")
            return
        if ui.safe(api.put, f"/api/v1/courses/{key}", changes):
            for k in [k for k in st.session_state if key in str(k)]:
                del st.session_state[k]
            _reload_courses()
            ui.flash(f"Course {course['code']} saved.", "✅")
            st.rerun()
    if course.get("is_active", True):
        if archive.button("Archive course", key=f"ec-archive-{key}", use_container_width=True):
            _confirm_archive(course, True)
    elif archive.button("Restore course", key=f"ec-restore-{key}", use_container_width=True):
        _confirm_archive(course, False)


def _courses_tab() -> None:
    with st.expander("➕ Create a course"):
        _create_course()
    archived = st.toggle("Show archived courses", key="manage-archived")
    courses = ui.safe(api.get_all, "/api/v1/courses/", is_active=not archived, default=[])
    st.markdown(f"**{len(courses)} {'archived' if archived else 'active'} course(s)**")
    if not courses:
        return
    frame = pd.DataFrame([{
        "Code": c.get("code"), "Name": c.get("name"), "Semester": c.get("semester"),
        "Instructor": c.get("instructor_name") or "—",
        "Default location": (c.get("venue_name") or "📍 set") if course_location(c) else "—",
        "Radius (m)": c.get("geofence_radius_meters"),
        "Face required": bool(c.get("require_face_recognition")),
    } for c in courses])
    st.dataframe(frame, hide_index=True, use_container_width=True,
                 column_config={"Radius (m)": st.column_config.NumberColumn(format="%.0f"),
                                "Face required": st.column_config.CheckboxColumn()})
    course = ui.pick("Edit a course", courses, ui.course_label, key="manage-course")
    if course:
        with st.container(border=True):
            _edit_course(course)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@st.dialog("Confirm")
def _confirm_user(user: dict, action: str, body: dict | None = None) -> None:
    who = f"**{ui.md(user['full_name'])}** ({ui.md(user['email'])})"
    texts = {
        "role": (f"Change {who} to **{ROLE_LABELS.get((body or {}).get('role'), '')}**?",
                 "Their new role applies from their next request. Course assignments stay as they are."),
        "deactivate": (f"Deactivate {who}?",
                       "They are signed out everywhere and can't sign in until reactivated. Nothing is deleted."),
        "activate": (f"Reactivate {who}?",
                     "They can sign in again. This also unlocks an account locked after failed sign-ins and "
                     "cancels a pending account deletion."),
    }
    question, explanation = texts[action]
    st.write(question)
    st.caption(explanation)
    left, right = st.columns(2)
    if left.button("Confirm", type="primary", use_container_width=True):
        path = f"/api/v1/users/{user['id']}" if action == "role" else f"/api/v1/admin/users/{user['id']}/{action}"
        if ui.safe(api.patch, path, body) is not None:
            ui.flash({"role": "Role changed.", "deactivate": "Account deactivated.",
                      "activate": "Account reactivated."}[action], "✅")
            st.rerun()
    if right.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Delete account")
def _confirm_delete_user(user: dict) -> None:
    st.write(f"Delete **{ui.md(user['full_name'])}**'s account?")
    st.caption("The account is deactivated now and its personal data (name, email, devices) is anonymised "
               "after 30 days by the automatic clean-up. Attendance records stay, without the name. "
               "Until then, Reactivate cancels the deletion.")
    typed = st.text_input(f"Type their email to confirm: {user['email']}")
    left, right = st.columns(2)
    if left.button("Delete account", type="primary", use_container_width=True,
                   disabled=typed.strip().lower() != user["email"].lower()):
        result = ui.safe(api.delete, f"/api/v1/users/{user['id']}")
        if result:
            ui.flash(f"Account deleted. Personal data will be removed on "
                     f"{ui.fmt_time(result.get('scheduled_deletion_at'), '%d %b %Y')}.", "🗑️")
            st.rerun()
    if right.button("Cancel", use_container_width=True):
        st.rerun()


def _user_detail(user_id: str) -> None:
    user = ui.safe(api.get, f"/api/v1/users/{user_id}")
    if not user:
        return
    me = user["id"] == auth.user().get("id")
    with st.container(border=True):
        st.markdown(f"**{ui.md(user['full_name'])}** · {ui.md(user['email'])}")
        devices = ui.safe(api.get, "/api/v1/devices/", user_id=user["id"], limit=100) or {}
        ui.metric_row([
            ("Role", ROLE_LABELS.get(user.get("role"), user.get("role")), None),
            ("Account", "🟢 Active" if user.get("is_active") else "⛔ Deactivated",
             "Deactivated accounts can't sign in. A deleted account stays deactivated until it's anonymised."),
            ("Face registered", "Yes" if user.get("face_enrolled") else "No", None),
            ("Devices", devices.get("total", 0), "Phones/browsers registered to this account (Devices tab)."),
        ])
        st.caption(f"Created {ui.fmt_time(user.get('created_at'))} · camera consent "
                   f"{'yes' if user.get('camera_consent') else 'no'} · location consent "
                   f"{'yes' if user.get('geolocation_consent') else 'no'}")
        if me:
            st.info("This is your own account, so it can't be changed here (so you can't lock yourself out).",
                    icon="🔒")
            return
        role_col, button_col, status_col, delete_col = st.columns([1.4, 1, 1, 1], vertical_alignment="bottom")
        roles = list(ROLE_LABELS)
        new_role = role_col.selectbox("Role", roles, index=roles.index(user["role"]) if user["role"] in roles else 0,
                                      format_func=ROLE_LABELS.get, key=f"role-{user['id']}")
        if button_col.button("Change role", disabled=new_role == user["role"], use_container_width=True,
                             key=f"role-btn-{user['id']}"):
            _confirm_user(user, "role", {"role": new_role})
        if user.get("is_active"):
            if status_col.button("Deactivate", use_container_width=True, key=f"deact-{user['id']}"):
                _confirm_user(user, "deactivate")
        elif status_col.button("Reactivate", type="primary", use_container_width=True, key=f"act-{user['id']}"):
            _confirm_user(user, "activate")
        if delete_col.button("Delete account", use_container_width=True, key=f"del-{user['id']}"):
            _confirm_delete_user(user)


def _users_tab() -> None:
    search_col, role_col, state_col = st.columns([2, 1, 1])
    search = search_col.text_input("Search name or email", key="manage-user-search")
    role = role_col.selectbox("Role", [None] + list(ROLE_LABELS), key="manage-user-role",
                              format_func=lambda r: "All roles" if r is None else ROLE_LABELS[r])
    state = state_col.selectbox("Account", [None, True, False], key="manage-user-active",
                                format_func=lambda v: {None: "All", True: "Active", False: "Deactivated"}[v])
    users = ui.safe(api.get_all, "/api/v1/users/", search=search.strip() or None, role=role, is_active=state,
                    default=[])
    st.markdown(f"**{len(users)} account(s)**")
    if not users:
        return
    frame = pd.DataFrame([{
        "Name": u.get("full_name"), "Email": u.get("email"), "Role": ROLE_LABELS.get(u.get("role"), u.get("role")),
        "Active": bool(u.get("is_active")), "Face": bool(u.get("face_enrolled")), "Created": u.get("created_at"),
    } for u in users])
    ui.local_datetime_column(frame, "Created")
    event = st.dataframe(frame, hide_index=True, use_container_width=True, on_select="rerun",
                         selection_mode="single-row", key="manage-users-table",
                         column_config={"Active": st.column_config.CheckboxColumn(),
                                        "Face": st.column_config.CheckboxColumn("Face registered"),
                                        "Created": st.column_config.DatetimeColumn(format="D MMM YYYY")})
    picked = event.selection.rows if event and event.selection else []
    if not picked:
        st.caption("Tick the box at the left of a row to see and change that account.")
        return
    _user_detail(users[picked[0]]["id"])


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

@st.dialog("Confirm")
def _confirm_device(device: dict, action: str) -> None:
    name = device.get("device_name") or device.get("browser") or "this device"
    texts = {
        "trust": (f"Mark **{ui.md(name)}** as trusted?",
                  "Check-ins from it no longer get the 'untrusted device' risk signal."),
        "untrust": (f"Mark **{ui.md(name)}** as not trusted?",
                    "Check-ins from it get the 'untrusted device' risk signal again."),
        "revoke": (f"Revoke **{ui.md(name)}**?",
                   "For a lost or shared phone: it can't be used for check-in any more. The student has to "
                   "register a device again on their next sign-in. Its history is kept."),
    }
    question, explanation = texts[action]
    st.write(question)
    st.caption(explanation)
    left, right = st.columns(2)
    if left.button("Revoke" if action == "revoke" else "Confirm", type="primary", use_container_width=True):
        path = f"/api/v1/devices/{device['id']}"
        call = (lambda: api.delete(path)) if action == "revoke" else \
            (lambda: api.patch(path, {"is_trusted": action == "trust"}))
        if ui.safe(call, default=False) is not False:
            ui.flash({"trust": "Device trusted.", "untrust": "Device no longer trusted.",
                      "revoke": "Device revoked."}[action], "✅")
            st.rerun()
    if right.button("Cancel", use_container_width=True):
        st.rerun()


def _devices_tab() -> None:
    st.caption("The backend doesn't say whose a device is in the full list, so pick an account to see theirs.")
    search = st.text_input("Find an account (name or email)", key="manage-device-search")
    people = ui.safe(api.get, "/api/v1/users/", search=search.strip() or None, limit=100, default={}) or {}
    by_id = {u["id"]: u for u in people.get("items", [])}
    # "" (not None) for "all": Streamlit shows a None value as "nothing picked yet".
    owner = st.selectbox("Account", [""] + list(by_id), key="manage-device-owner",
                         format_func=lambda uid: "All accounts" if not uid
                         else f"{by_id[uid]['full_name']} · {by_id[uid]['email']} · {ROLE_LABELS.get(by_id[uid]['role'])}")
    owner = owner or None
    trust_col, active_col = st.columns(2)
    trusted = trust_col.selectbox("Trusted", [None, True, False], key="manage-device-trusted",
                                  format_func=lambda v: {None: "All", True: "Trusted", False: "Not trusted"}[v])
    active = active_col.selectbox("State", [True, None, False], key="manage-device-active",
                                  format_func=lambda v: {None: "All", True: "In use", False: "Revoked"}[v])
    devices = ui.safe(api.get_all, "/api/v1/devices/", user_id=owner, is_trusted=trusted, is_active=active,
                      default=[])
    st.markdown(f"**{len(devices)} device(s)**")
    if not devices:
        return
    frame = pd.DataFrame([{
        "Device": d.get("device_name") or "—", "Platform": d.get("platform") or "—",
        "Browser / OS": " · ".join(x for x in (d.get("browser"), d.get("os_version")) if x) or "—",
        "Trusted": bool(d.get("is_trusted")), "In use": bool(d.get("is_active")),
        "Check-ins": d.get("total_checkins", 0), "First seen": d.get("first_seen_at"), "Last seen": d.get("last_seen_at"),
    } for d in devices])
    ui.local_datetime_column(frame, "First seen", "Last seen")
    event = st.dataframe(frame, hide_index=True, use_container_width=True, on_select="rerun",
                         selection_mode="single-row", key=f"manage-devices-{owner}",
                         column_config={"Trusted": st.column_config.CheckboxColumn(),
                                        "In use": st.column_config.CheckboxColumn(),
                                        "First seen": st.column_config.DatetimeColumn(format="D MMM YYYY"),
                                        "Last seen": st.column_config.DatetimeColumn(format="D MMM YYYY, HH:mm")})
    picked = event.selection.rows if event and event.selection else []
    if not picked:
        st.caption("Tick a row to trust or revoke that device.")
        return
    device = devices[picked[0]]
    trust_btn, revoke_btn, _ = st.columns([1, 1, 2])
    if device.get("is_trusted"):
        if trust_btn.button("Mark not trusted", use_container_width=True):
            _confirm_device(device, "untrust")
    elif trust_btn.button("Mark trusted", use_container_width=True, disabled=not device.get("is_active")):
        _confirm_device(device, "trust")
    if revoke_btn.button("Revoke device", use_container_width=True, disabled=not device.get("is_active")):
        _confirm_device(device, "revoke")


def render() -> None:
    ui.header("MANAGE", "Users & courses", "Create and edit courses, manage accounts and registered devices.")
    courses, users, devices = st.tabs(["Courses", "Users", "Devices"])
    with courses:
        _courses_tab()
    with users:
        _users_tab()
    with devices:
        _devices_tab()
