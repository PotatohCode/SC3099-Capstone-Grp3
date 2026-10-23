"""Seed the local test accounts, courses and today's sessions through the API.

Safe to re-run: existing users, courses and enrollments are reused, and a
session is only created if one with the same name doesn't exist yet. Session
names carry today's date, so each day's run opens fresh check-in windows.

    python module2-backend/scripts/seed_test_accounts.py [--base-url http://localhost:8000]
"""
import argparse
from datetime import datetime, timedelta, timezone

import httpx

PASSWORD = "SaivTest#2026"
NTU = (1.3483, 103.6831)

USERS = [  # local test accounts only; names match the original manual seed
    ("admin@saiv-test.edu", "Alex Admin", "admin"),
    ("instructor@saiv-test.edu", "Ivy Instructor", "instructor"),
    ("ta@saiv-test.edu", "Tom TA", "ta"),
    ("student1@saiv-test.edu", "Sam Student", "student"),
    ("student2@saiv-test.edu", "Sara Student", "student"),
    ("student3@saiv-test.edu", "Sid NotEnrolled", "student"),
]

# code -> (name, members enrolled; the TA's enrollment is its staff assignment)
COURSES = {
    "SC3099": ("Capstone Project", ["student1", "student2", "ta"]),
    "SC2006": ("Software Engineering", ["student1"]),
}

# (course code, session name, session_type)
SESSIONS = [
    ("SC3099", "Lecture", "lecture"),
    ("SC3099", "Tutorial", "tutorial"),
    ("SC2006", "Lecture", "lecture"),
]


def check(resp: httpx.Response, *ok_codes: str) -> dict | None:
    if resp.is_success:
        return resp.json() if resp.content else None
    body = resp.json() if resp.content else {}
    if body.get("code") in ok_codes:
        return None
    raise SystemExit(f"{resp.request.method} {resp.request.url} -> {resp.status_code} {body}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    api = httpx.Client(base_url=f"{args.base_url}/api/v1", timeout=30)

    ids = {}
    for email, name, role in USERS:
        check(api.post("/auth/register", json={"email": email, "password": PASSWORD, "full_name": name, "role": role}),
              "EMAIL_ALREADY_REGISTERED")
        login = check(api.post("/auth/login", json={"email": email, "password": PASSWORD}))
        ids[email.split("@")[0]] = login["user"]["id"]
        if login["user"]["full_name"] != name:  # an earlier run used other names
            check(api.put("/users/me", json={"full_name": name},
                          headers={"Authorization": f"Bearer {login['access_token']}"}))
        if email.startswith("admin@"):
            admin_token = login["access_token"]
        print(f"user   {role:10} {email}")

    auth = {"Authorization": f"Bearer {admin_token}"}
    # Filter to our instructor: the test suites leave hundreds of other courses behind.
    existing = {c["code"]: c["id"] for c in check(api.get(
        "/courses/", params={"instructor_id": ids["instructor"], "limit": 100}, headers=auth))["items"]}
    course_ids = {}
    for code, (name, members) in COURSES.items():
        if code not in existing:
            created = check(api.post("/courses/", headers=auth, json={
                "code": code, "name": name, "semester": "AY26/27 S1", "instructor_id": ids["instructor"],
                "venue_name": "NTU", "venue_latitude": NTU[0], "venue_longitude": NTU[1],
                "geofence_radius_meters": 150,
            }))
            existing[code] = created["id"]
        course_ids[code] = existing[code]
        for member in members:
            check(api.post("/admin/enrollments/", headers=auth,
                           json={"student_id": ids[member], "course_id": course_ids[code]}), "ALREADY_ENROLLED")
        print(f"course {code} ({', '.join(members)})")

    now = datetime.now(timezone.utc)
    today = now.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    sessions = [s for code in course_ids for s in check(api.get(
        "/sessions/", params={"course_id": course_ids[code], "limit": 100}, headers=auth))["items"]]
    for code, name, kind in SESSIONS:
        full_name = f"{name} {today}"
        match = next((s for s in sessions if s["course_id"] == course_ids[code] and s["name"] == full_name), None)
        if match is None:
            match = check(api.post("/sessions/", headers=auth, json={
                "course_id": course_ids[code], "name": full_name, "session_type": kind,
                "scheduled_start": now.isoformat(), "scheduled_end": (now + timedelta(hours=2)).isoformat(),
                "checkin_opens_at": (now - timedelta(minutes=5)).isoformat(),
                "checkin_closes_at": (now + timedelta(hours=8)).isoformat(),
                "venue_name": "NTU", "venue_latitude": NTU[0], "venue_longitude": NTU[1],
                "geofence_radius_meters": 150,
            }))
        check(api.patch(f"/admin/sessions/{match['id']}/status", headers=auth, json={"status": "active"}))
        print(f"session {code} {full_name} -> active")

    print(f"\nDone. Password for every account: {PASSWORD}")


if __name__ == "__main__":
    main()
