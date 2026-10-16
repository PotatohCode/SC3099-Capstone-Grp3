"""Fill a LOCAL SAIV backend with demo data for the Module 4 portal.

Creates (through the normal backend API, so every rule and audit log applies):
- one account per role (logins below; local test values only),
- a course with 12 students and the TA enrolled,
- a closed past session, an active session students are checking in to,
  and a scheduled session,
- check-ins with a realistic mix of approved / flagged / rejected outcomes.

Safe to run more than once: existing accounts are reused.

    python module4-observability/scripts/seed_demo_data.py [--backend http://localhost:8000]

Uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "SaivDemo2026!"
ACCOUNTS = {
    "admin": ("admin@saiv.demo", "Ada Admin"),
    "instructor": ("instructor@saiv.demo", "Ian Instructor"),
    "ta": ("ta@saiv.demo", "Tara Assistant"),
}
STUDENTS = ["Wei Ling Tan", "Arjun Kumar", "Siti Rahman", "Jun Hao Lim", "Priya Nair", "Marcus Ong",
            "Hui Min Goh", "Daniel Lee", "Aisyah Ismail", "Ethan Ng", "Mei Xin Tan", "Ravi Kumar"]
NTU = (1.3483, 103.6831)

BACKEND = "http://localhost:8000"


def call(method: str, path: str, body: dict | None = None, token: str | None = None, ok=(200, 201, 204)):
    request = urllib.request.Request(f"{BACKEND}/api/v1{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as err:
        raw = err.read()
        payload = json.loads(raw) if raw else None
        if err.code in ok:
            return err.code, payload
        return err.code, payload


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def account(email: str, name: str, role: str) -> tuple[str, dict]:
    call("POST", "/auth/register", {"email": email, "password": PASSWORD, "full_name": name, "role": role})
    status, data = call("POST", "/auth/login", {"email": email, "password": PASSWORD})
    if status != 200:
        sys.exit(f"Can't sign in as {email}: {data}")
    return data["access_token"], data["user"]


def main() -> None:
    global BACKEND
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default=BACKEND)
    BACKEND = parser.parse_args().backend.rstrip("/")
    rng = random.Random(42)

    admin_token, _ = account(*ACCOUNTS["admin"], "admin")
    instructor_token, instructor = account(*ACCOUNTS["instructor"], "instructor")
    ta_token, ta = account(*ACCOUNTS["ta"], "ta")
    students = []
    for i, name in enumerate(STUDENTS):
        email = f"{name.lower().replace(' ', '.')}@e.ntu.edu.sg"
        token, user = account(email, name, "student")
        students.append((token, user, i))

    # Course owned by the instructor (admin creates it, then assigns).
    status, courses = call("GET", "/courses/?limit=100")
    course = next((c for c in courses["items"] if c["code"] == "SC3099"), None)
    if course is None:
        _, course = call("POST", "/courses/", {
            "code": "SC3099", "name": "Capstone Project", "semester": "AY2026-27 Sem 1",
            "venue_name": "LT26", "venue_latitude": NTU[0], "venue_longitude": NTU[1],
            "geofence_radius_meters": 150}, admin_token)
    call("PUT", f"/courses/{course['id']}", {"instructor_id": instructor["id"]}, admin_token)

    emails = [s[1]["email"] for s in students] + [ta["email"]]
    call("POST", "/enrollments/bulk", {"course_id": course["id"], "student_emails": emails}, instructor_token)

    now = datetime.now(timezone.utc)

    # Re-running: close sessions left open by an earlier seed run.
    _, existing = call("GET", f"/sessions/?course_id={course['id']}&limit=100", token=instructor_token)
    week = sum(1 for o in (existing or {}).get("items", []) if "Lecture" in o["name"]) + 1
    for old in (existing or {}).get("items", []):
        if old["status"] in ("active", "scheduled"):
            call("PATCH", f"/sessions/{old['id']}", {"status": "closed" if old["status"] == "active" else "cancelled"},
                 instructor_token)

    def new_session(name: str, start: datetime, opens_before: int = 15) -> dict:
        _, session = call("POST", "/sessions/", {
            "course_id": course["id"], "name": name, "session_type": "lecture",
            "scheduled_start": iso(start), "scheduled_end": iso(start + timedelta(hours=2)),
            "checkin_opens_at": iso(start - timedelta(minutes=opens_before)),
            "checkin_closes_at": iso(start + timedelta(minutes=60)),
            "venue_name": "LT26", "venue_latitude": NTU[0], "venue_longitude": NTU[1],
            "geofence_radius_meters": 150, "require_liveness_check": True, "require_face_match": False,
        }, instructor_token)
        if not session or "id" not in session:
            sys.exit(f"Couldn't create session {name}: {session}")
        return session

    photo = (ROOT / "sample_images" / "obama.jpg").read_bytes()

    def check_in(session: dict, token: str, index: int, kind: str) -> None:
        # Each student sits at a fixed spot, so consecutive check-ins never look
        # like "impossible travel".
        lat, lon, accuracy = NTU[0] + 0.00004 * (index % 4), NTU[1] + 0.00004 * (index // 4), 15.0
        if kind == "far":         # 1-2x the geofence radius -> flagged
            lat += 0.0018
        if kind == "very_far":    # more than 2x the radius -> rejected
            lat += 0.006
        if kind == "spoof":       # suspiciously perfect accuracy -> flagged
            accuracy = 0.5
        # A fresh camera frame each time: identical bytes would be a replay.
        frame = photo + rng.randbytes(16)
        call("POST", "/checkins/", {
            "session_id": session["id"], "latitude": lat, "longitude": lon,
            "location_accuracy_meters": accuracy, "device_fingerprint": f"seed-device-{index:02d}",
            "liveness_challenge_response": base64.b64encode(frame).decode(),
        }, token)

    for token, _, index in students:
        call("POST", "/devices/register", {"device_fingerprint": f"seed-device-{index:02d}",
                                           "device_name": "Demo phone", "platform": "android"}, token)

    # Each check-in needs an open session; create them just in time, run them, then close.
    plan = ["ok"] * 8 + ["far", "spoof", "very_far"]
    past = new_session(f"Week {week} Lecture", now + timedelta(minutes=2))
    call("PATCH", f"/sessions/{past['id']}", {"status": "active"}, instructor_token)
    for (token, _, index), kind in zip(students, rng.sample(plan, len(plan))):
        check_in(past, token, index, kind)
    call("PATCH", f"/sessions/{past['id']}", {"status": "closed"}, instructor_token)

    live = new_session(f"Week {week + 1} Lecture", now + timedelta(minutes=3))
    call("PATCH", f"/sessions/{live['id']}", {"status": "active"}, instructor_token)
    live_plan = ["ok"] * 6 + ["far", "spoof", "far"]
    for (token, _, index), kind in zip(students[:9], live_plan):
        check_in(live, token, index, kind)

    new_session(f"Week {week + 1} Tutorial", now + timedelta(days=1))

    # A few failed sign-ins so the security panels have something to show.
    for _ in range(3):
        call("POST", "/auth/login", {"email": ACCOUNTS["ta"][0], "password": "wrong-password"})

    print("Seeded SAIV demo data.\n")
    print(f"  Portal:  http://localhost:8501   (password for every account: {PASSWORD})")
    for role, (email, _) in ACCOUNTS.items():
        print(f"  {role:<11} {email}")
    print(f"  student     {students[0][1]['email']} (and {len(students) - 1} more)")


if __name__ == "__main__":
    main()
