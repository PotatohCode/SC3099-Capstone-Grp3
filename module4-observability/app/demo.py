"""Preview mode: a small in-memory copy of the backend API with realistic
sample data, so the portal can be explored (or demoed) without a running
backend. Only active when DEMO_MODE=true and "Explore with sample data" is
chosen; actions (review, activate, create...) change this copy only."""
from __future__ import annotations

import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import streamlit as st

import api

ME = "demo-instructor"
FIRST = ["Wei Ling", "Arjun", "Siti", "Jun Hao", "Priya", "Marcus", "Hui Min", "Daniel", "Aisyah", "Ethan",
         "Mei Xin", "Ravi", "Chloe", "Irfan", "Shu Fen", "Kai", "Nadia", "Bryan", "Yi Xuan", "Farhan"]
LAST = ["Tan", "Kumar", "Rahman", "Lim", "Nair", "Ong", "Goh", "Lee", "Ismail", "Ng"]
FACTORS = ["device_unknown", "geo_accuracy_low", "unusual_time", "geo_out_of_bounds", "rapid_succession",
           "liveness_unverified", "gps_spoof_suspected"]


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def _level(score: float) -> str:
    return "LOW" if score < 0.3 else "MEDIUM" if score < 0.5 else "HIGH" if score < 0.7 else "CRITICAL"


def _build() -> dict:
    rng = random.Random(3099)
    now = datetime.now(timezone.utc)
    courses = [
        {"id": "c-sc3099", "code": "SC3099", "name": "Capstone Project", "semester": "AY2026-27 Sem 1",
         "instructor_id": ME, "is_active": True},
        {"id": "c-sc2006", "code": "SC2006", "name": "Software Engineering", "semester": "AY2026-27 Sem 1",
         "instructor_id": ME, "is_active": True},
    ]
    students = []
    for i in range(40):
        name = f"{FIRST[i % len(FIRST)]} {LAST[(i * 3) % len(LAST)]}"
        students.append({"id": f"s-{i:02d}", "name": name,
                         "email": f"{name.lower().replace(' ', '.')}{i}@e.ntu.edu.sg"})
    enrollments = [{"id": f"e-{c['id']}-{s['id']}", "course_id": c["id"], "student_id": s["id"],
                    "enrolled_at": _iso(now - timedelta(days=60))}
                   for c in courses for s in (students[:28] if c["id"] == "c-sc3099" else students[20:])]

    sessions, checkins = [], []
    for course in courses:
        for week in range(6, 0, -1):
            start = (now - timedelta(days=7 * week)).replace(hour=1, minute=30, second=0, microsecond=0)
            sessions.append(_session(course, f"Week {13 - week} Lecture", start, "closed"))
        sessions.append(_session(course, "Week 13 Lecture", now - timedelta(minutes=20), "active"))
        sessions.append(_session(course, "Week 13 Tutorial", now + timedelta(hours=3), "scheduled"))
    for session in sessions:
        if session["status"] == "scheduled":
            continue
        roster = [e["student_id"] for e in enrollments if e["course_id"] == session["course_id"]]
        attending = rng.sample(roster, int(len(roster) * rng.uniform(0.72, 0.95)))
        for sid in attending:
            score = round(min(rng.betavariate(1.3, 6) + (0.35 if rng.random() < 0.08 else 0), 0.95), 2)
            status = "approved" if score < 0.3 else "flagged" if score < 0.7 else "rejected"
            if session["status"] == "closed" and status == "flagged" and rng.random() < 0.7:
                status = rng.choice(["approved", "rejected"])
            factors = [{"type": t, "weight": 0.1} for t in rng.sample(FACTORS, 1 + int(score > 0.4))] if score >= 0.3 else []
            opened = datetime.fromisoformat(session["checkin_opens_at"]).replace(tzinfo=timezone.utc)
            checkins.append({
                "id": str(uuid.UUID(int=rng.getrandbits(128))), "session_id": session["id"], "student_id": sid,
                "status": status, "risk_score": score, "risk_factors": factors,
                "checked_in_at": _iso(opened + timedelta(minutes=rng.uniform(1, 35))),
                "distance_from_venue_meters": round(rng.uniform(3, 60) + (150 if "geo_out_of_bounds" in str(factors) else 0)),
                "appeal_reason": "I was in the lecture, my phone's GPS was slow." if status == "flagged" and rng.random() < 0.2 else None,
                "entry_method": "app",
            })
    for c in checkins:
        if c["appeal_reason"]:
            c["status"] = "appealed"
    return {"courses": courses, "students": {s["id"]: s for s in students}, "enrollments": enrollments,
            "sessions": sessions, "checkins": checkins}


def _session(course: dict, name: str, start: datetime, status: str) -> dict:
    return {
        "id": f"ses-{uuid.uuid4().hex[:10]}", "course_id": course["id"], "course_code": course["code"],
        "course_name": course["name"], "instructor_id": ME, "name": name, "session_type": "lecture",
        "status": status, "scheduled_start": _iso(start), "scheduled_end": _iso(start + timedelta(hours=2)),
        "checkin_opens_at": _iso(start - timedelta(minutes=15)), "checkin_closes_at": _iso(start + timedelta(minutes=30)),
        "venue_name": "LT26", "require_liveness_check": True, "require_face_match": False,
    }


def _db() -> dict:
    if "demo_db" not in st.session_state:
        st.session_state.demo_db = _build()
    return st.session_state.demo_db


def _page(items: list, params: dict | None) -> dict:
    params = params or {}
    limit, offset = int(params.get("limit", 100)), int(params.get("offset", 0))
    return {"items": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}


def _enriched(db: dict, c: dict) -> dict:
    session = next(s for s in db["sessions"] if s["id"] == c["session_id"])
    student = db["students"][c["student_id"]]
    return {**c, "session_name": session["name"], "student_name": student["name"],
            "student_email": student["email"], "risk_level": _level(c["risk_score"])}


def _session_view(db: dict, s: dict) -> dict:
    enrolled = sum(1 for e in db["enrollments"] if e["course_id"] == s["course_id"])
    checked = sum(1 for c in db["checkins"] if c["session_id"] == s["id"])
    return {**s, "total_enrolled": enrolled, "checked_in_count": checked}


def _session_stats(db: dict, s: dict) -> dict:
    rows = [c for c in db["checkins"] if c["session_id"] == s["id"]]
    enrolled = sum(1 for e in db["enrollments"] if e["course_id"] == s["course_id"])
    by_status = {k: sum(1 for c in rows if c["status"] == k) for k in ("approved", "flagged", "rejected", "pending", "appealed")}
    attended = sum(1 for c in rows if c["status"] != "rejected")
    opened = datetime.fromisoformat(s["checkin_opens_at"])
    buckets: dict[int, int] = {}
    for c in rows:
        minute = int((datetime.fromisoformat(c["checked_in_at"]) - opened).total_seconds() // 300) * 5
        buckets[minute] = buckets.get(minute, 0) + 1
    return {
        "session_id": s["id"], "session_name": s["name"], "total_enrolled": enrolled,
        "checked_in": len(rows), "checked_in_count": len(rows), "approved_count": by_status["approved"],
        "flagged_count": by_status["flagged"] + by_status["appealed"],
        "attendance_rate": round(attended / enrolled, 4) if enrolled else 0.0, "by_status": by_status,
        "average_risk_score": round(sum(c["risk_score"] for c in rows) / len(rows), 3) if rows else None,
        "risk_distribution": {"low": sum(c["risk_score"] < 0.3 for c in rows),
                              "medium": sum(0.3 <= c["risk_score"] < 0.5 for c in rows),
                              "high": sum(c["risk_score"] >= 0.5 for c in rows)},
        "checkin_timeline": [{"minute": m, "count": n} for m, n in sorted(buckets.items())],
    }


def _course_stats(db: dict, course: dict) -> dict:
    sessions = [s for s in db["sessions"] if s["course_id"] == course["id"] and s["status"] != "scheduled"]
    roster = [e["student_id"] for e in db["enrollments"] if e["course_id"] == course["id"]]
    per_session = [_session_stats(db, s) for s in sessions]
    students = []
    for sid in roster:
        mine = [c for c in db["checkins"] if c["student_id"] == sid and c["session_id"] in {s["id"] for s in sessions}]
        attended = sum(1 for c in mine if c["status"] != "rejected")
        rate = attended / len(sessions) if sessions else 0
        students.append({"student_id": sid, "student_name": db["students"][sid]["name"], "sessions_attended": attended,
                         "attendance_rate": round(rate, 4),
                         "average_risk_score": round(sum(c["risk_score"] for c in mine) / len(mine), 3) if mine else 0})
    rate = sum(p["attendance_rate"] for p in per_session) / len(per_session) if per_session else 0
    return {
        "course_id": course["id"], "course_code": course["code"], "course_name": course["name"],
        "total_sessions": len(sessions), "total_enrolled": len(roster),
        "overall_attendance_rate": round(rate, 4), "average_attendance_rate": round(rate, 4),
        "flagged_checkins": sum(p["flagged_count"] for p in per_session),
        "sessions": [{"session_id": s["id"], "name": s["name"], "date": s["scheduled_start"][:10],
                      "attendance_rate": p["attendance_rate"], "checked_in": p["checked_in"]}
                     for s, p in zip(sessions, per_session)],
        "student_attendance": students,
        "low_attendance_alerts": [{"student_id": s["student_id"], "student_name": s["student_name"],
                                   "attendance_rate": s["attendance_rate"],
                                   "sessions_missed": len(sessions) - s["sessions_attended"]}
                                  for s in students if s["attendance_rate"] < 0.75],
    }


def _overview(db: dict) -> dict:
    now = datetime.now(timezone.utc)
    days = [(now - timedelta(days=d)).date() for d in range(6, -1, -1)]
    by_day = {d: [c for c in db["checkins"] if c["checked_in_at"][:10] == d.isoformat()] for d in days}
    approved = sum(c["status"] == "approved" for c in db["checkins"])
    return {
        "total_sessions": len(db["sessions"]), "active_sessions": sum(s["status"] == "active" for s in db["sessions"]),
        "total_courses": len(db["courses"]), "total_students": len(db["students"]),
        "today_checkins": len(by_day[days[-1]]),
        "flagged_pending": sum(c["status"] in ("flagged", "appealed") for c in db["checkins"]),
        "approval_rate": round(approved / len(db["checkins"]), 4),
        "average_attendance_rate": _course_stats(db, db["courses"][0])["average_attendance_rate"],
        "trends": {
            "checkins_by_day": [{"date": d.isoformat(), "count": len(by_day[d])} for d in days],
            "attendance_rate_by_day": [
                {"date": d.isoformat(), "rate": round(sum(c["status"] != "rejected" for c in by_day[d]) / 28, 4)}
                for d in days if by_day[d]],
        },
    }


def _export_records(db: dict, session_ids: set[str]) -> list[dict]:
    rows = []
    for c in sorted(db["checkins"], key=lambda c: c["checked_in_at"]):
        if c["session_id"] in session_ids:
            s = next(x for x in db["sessions"] if x["id"] == c["session_id"])
            student = db["students"][c["student_id"]]
            rows.append({"student_id": c["student_id"], "student_name": student["name"],
                         "student_email": student["email"], "session_date": s["scheduled_start"][:10],
                         "session_name": s["name"], "status": c["status"], "checked_in_at": c["checked_in_at"],
                         "risk_score": c["risk_score"]})
    return rows


def handle(method: str, path: str, params: dict | None = None, body: dict | None = None, raw: bool = False):
    db = _db()
    path = path.replace("/api/v1", "", 1).rstrip("/") or "/"
    params = params or {}

    def find(collection: str, item_id: str) -> dict:
        found = next((x for x in db[collection] if x["id"] == item_id), None)
        if found is None:
            raise api.ApiError("That record no longer exists.", 404)
        return found

    if method == "GET" and path == "/stats/overview":
        return _overview(db)
    if method == "GET" and path == "/courses":
        return _page(db["courses"], params)
    if method == "GET" and path == "/sessions":
        items = [_session_view(db, s) for s in db["sessions"]]
        if params.get("status"):
            items = [s for s in items if s["status"] == params["status"]]
        if params.get("course_id"):
            items = [s for s in items if s["course_id"] == params["course_id"]]
        if params.get("start_date"):
            items = [s for s in items if s["scheduled_start"] >= params["start_date"]]
        if params.get("end_date"):
            items = [s for s in items if s["scheduled_start"] <= params["end_date"]]
        return _page(sorted(items, key=lambda s: s["scheduled_start"], reverse=True), params)
    if method == "POST" and path == "/sessions":
        course = find("courses", body["course_id"])
        start = datetime.fromisoformat(body["scheduled_start"]).replace(tzinfo=timezone.utc)
        session = {**_session(course, body["name"], start, "scheduled"), **{k: v for k, v in body.items() if v is not None}}
        db["sessions"].append(session)
        return _session_view(db, session)
    if m := re.fullmatch(r"/sessions/([^/]+)", path):
        session = find("sessions", m[1])
        if method == "PATCH":
            session.update(body)
        return _session_view(db, session)
    if m := re.fullmatch(r"/stats/sessions/([^/]+)", path):
        return _session_stats(db, find("sessions", m[1]))
    if m := re.fullmatch(r"/checkins/session/([^/]+)", path):
        return [_enriched(db, c) for c in db["checkins"] if c["session_id"] == m[1]]
    if method == "GET" and path == "/checkins/flagged":
        items = [_enriched(db, c) for c in db["checkins"] if c["status"] in ("flagged", "appealed")]
        for item in items:
            item["risk_factors"] = [{**f, "severity": "medium"} for f in item["risk_factors"]]
        return _page(sorted(items, key=lambda c: c["checked_in_at"], reverse=True), params)
    if method == "POST" and path == "/checkins/manual":
        existing = next((c for c in db["checkins"] if c["session_id"] == body["session_id"]
                         and c["student_id"] == body["student_id"]), None)
        if existing and existing["status"] == "approved":
            raise api.ApiError("Student already checked in", 400, "ALREADY_CHECKED_IN")
        if existing:
            existing["previous"] = {k: existing.get(k) for k in ("status", "entry_method", "risk_factors")}
            existing.update(status="approved", entry_method="override",
                            risk_factors=existing["risk_factors"] + [{"type": "manual_override", "weight": 0}])
            checkin, code = existing, 200
        else:
            checkin = {"id": str(uuid.uuid4()), "session_id": body["session_id"], "student_id": body["student_id"],
                       "status": "approved", "entry_method": "manual", "risk_score": 0.0,
                       "risk_factors": [{"type": "manual_checkin", "weight": 0}],
                       "checked_in_at": _iso(datetime.now(timezone.utc)), "distance_from_venue_meters": None,
                       "appeal_reason": None}
            db["checkins"].append(checkin)
            code = 201
        return SimpleNamespace(status_code=code, json=lambda: checkin) if raw else checkin
    if m := re.fullmatch(r"/checkins/([^/]+)/manual/undo", path):
        checkin = find("checkins", m[1])
        if checkin.get("entry_method") == "manual":
            db["checkins"].remove(checkin)
            return {"id": checkin["id"], "status": "deleted"}
        if checkin.get("entry_method") == "override":
            checkin.update(checkin.pop("previous"))
            return {"id": checkin["id"], "status": checkin["status"]}
        raise api.ApiError("Only manual check-ins and overrides can be undone", 400, "MANUAL_UNDO_NOT_ALLOWED")
    if m := re.fullmatch(r"/users/([^/]+)/face/reset-code", path):
        code = "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
        return {"student_id": m[1], "code": f"{code[:4]}-{code[4:]}",
                "expires_at": _iso(datetime.now(timezone.utc) + timedelta(hours=24))}
    if m := re.fullmatch(r"/checkins/([^/]+)/review", path):
        checkin = find("checkins", m[1])
        checkin["status"] = body["status"]
        return {"id": checkin["id"], "status": checkin["status"]}
    if m := re.fullmatch(r"/stats/courses/([^/]+)", path):
        return _course_stats(db, find("courses", m[1]))
    if m := re.fullmatch(r"/enrollments/course/([^/]+)", path):
        course = find("courses", m[1])
        rows = [{"id": e["id"], "student_id": e["student_id"], "student_name": db["students"][e["student_id"]]["name"],
                 "student_email": db["students"][e["student_id"]]["email"], "enrolled_at": e["enrolled_at"],
                 "is_active": True, "face_enrolled": hash(e["student_id"]) % 5 != 0}
                for e in db["enrollments"] if e["course_id"] == course["id"]]
        return {"course_id": course["id"], "course_code": course["code"], "total_enrolled": len(rows), "students": rows}
    if method == "POST" and path == "/enrollments/bulk":
        by_email = {s["email"]: sid for sid, s in db["students"].items()}
        result = {"enrolled": 0, "already_enrolled": 0, "not_found": 0, "created": 0, "details": []}
        for email in body["student_emails"]:
            sid = by_email.get(email)
            if sid is None:
                result["not_found"] += 1
                result["details"].append({"email": email, "status": "not_found"})
            elif any(e["student_id"] == sid and e["course_id"] == body["course_id"] for e in db["enrollments"]):
                result["already_enrolled"] += 1
                result["details"].append({"email": email, "status": "already_enrolled"})
            else:
                db["enrollments"].append({"id": f"e-{uuid.uuid4().hex[:8]}", "course_id": body["course_id"],
                                          "student_id": sid, "enrolled_at": _iso(datetime.now(timezone.utc))})
                result["enrolled"] += 1
                result["details"].append({"email": email, "status": "enrolled"})
        return result
    if method == "DELETE" and (m := re.fullmatch(r"/enrollments/([^/]+)", path)):
        db["enrollments"] = [e for e in db["enrollments"] if e["id"] != m[1]]
        return None
    if method == "POST" and path in ("/auth/register", "/admin/users/bulk"):
        users = body["users"] if path.endswith("bulk") else [body]
        created, errors = [], []
        emails = {s["email"] for s in db["students"].values()}
        for u in users:
            if u["email"] in emails:
                errors.append({"email": u["email"], "error": "Email already registered"})
                continue
            sid = f"s-{uuid.uuid4().hex[:8]}"
            db["students"][sid] = {"id": sid, "name": u["full_name"], "email": u["email"]}
            created.append({"id": sid, "email": u["email"], "full_name": u["full_name"], "role": u["role"]})
        if path == "/auth/register":
            if errors:
                raise api.ApiError(errors[0]["error"], 400)
            return created[0]
        return {"created": len(created), "failed": len(errors), "users": created, "errors": errors}
    if m := re.fullmatch(r"/stats/students/([^/]+)", path):
        student = db["students"].get(m[1]) or {"name": "Unknown", "email": ""}
        mine = [c for c in db["checkins"] if c["student_id"] == m[1]]
        attended = sum(c["status"] != "rejected" for c in mine)
        total = sum(1 for s in db["sessions"] if s["status"] != "scheduled" and any(
            e["student_id"] == m[1] and e["course_id"] == s["course_id"] for e in db["enrollments"]))
        recent = [{"session_name": _enriched(db, c)["session_name"], "course_code": next(
            s["course_code"] for s in db["sessions"] if s["id"] == c["session_id"]),
            "checked_in_at": c["checked_in_at"], "status": c["status"]}
            for c in sorted(mine, key=lambda c: c["checked_in_at"], reverse=True)[:10]]
        return {"student_id": m[1], "student_name": student["name"], "student_email": student["email"],
                "total_enrolled_courses": sum(e["student_id"] == m[1] for e in db["enrollments"]),
                "total_sessions": total, "attended_sessions": attended,
                "attendance_rate": round(attended / total, 4) if total else 0, "courses": [],
                "recent_sessions": recent, "recent_checkins": recent}
    if m := re.fullmatch(r"/export/session/([^/]+)", path):
        session = find("sessions", m[1])
        stats = _session_stats(db, session)
        return {"session_id": session["id"], "session_name": session["name"],
                "summary": {k: stats[k] for k in ("total_enrolled", "checked_in_count", "attendance_rate",
                                                   "approved_count", "flagged_count", "average_risk_score")},
                "records": _export_records(db, {session["id"]})}
    if m := re.fullmatch(r"/export/attendance/([^/]+)", path):
        return _export_records(db, {s["id"] for s in db["sessions"] if s["course_id"] == m[1]})
    raise api.ApiError("Not available in preview mode.", 404)


def prometheus_value(promql: str) -> float | None:
    # First matching marker wins (the flagged-rate query also mentions attempts).
    samples = {"checkins_flagged_total": 0.12, "checkin_attempts_total": 46, "login_failed_total": 7,
               "account_lockouts_total": 0, "checkin_rejected_geo_total": 2, "security_violations_total": 3,
               "histogram_quantile": 182.0, "5..": 0.0, 'job="saiv-face': 0.0, "up{": 1.0}
    for marker, value in samples.items():
        if marker in promql:
            return value
    return 0.0
