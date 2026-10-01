# Module 2 Backend API — For Module 4 (Observability Dashboard)

Read [API-CONVENTIONS.md](API-CONVENTIONS.md) first (auth, error format,
pagination). For **what changed and what you need to do**, see
[CHANGES-2026-10-01.md](CHANGES-2026-10-01.md) §1 and the Module 4 guide in
§4. Last updated 2026-10-01.

This covers the `/stats/*` analytics, `/export/*` data export, `/audit/*`
compliance log, and `/metrics` for Prometheus/Grafana. Everything here needs
**instructor, ta or admin**, and most endpoints narrow further (noted
below). Check-in lists and the review queue are in
[API-FOR-FRONTEND.md](API-FOR-FRONTEND.md) §7. The dashboard can use them
the same way (e.g. `GET /checkins/flagged` + `POST /checkins/{id}/review`
for a review screen).

---

## 1. Stats (`/api/v1/stats/*`)

**Read this before building against field names:** several fields appear
**under two names for the same value**, one matching the written spec and
one matching what the graded tests assert. Both are always present and
always equal, so use whichever you prefer.

### `GET /stats/overview` — instructor/ta/admin
Query: `course_id` (optional), `days` (1–365, default 7; controls the trend
window only).
```json
{
  "total_sessions": 0, "active_sessions": 0, "total_courses": 0, "total_students": 0,
  "today_checkins": 0, "flagged_pending": 0, "approval_rate": 0.0,
  "total_checkins_today": 0,        // == today_checkins
  "total_checkins_week": 0,
  "average_attendance_rate": 0.0,
  "flagged_pending_review": 0,      // == flagged_pending
  "average_risk_score": 0.0,
  "high_risk_checkins_today": 0,    // risk_score >= 0.5
  "trends": {
    "checkins_by_day": [{ "date": "2026-10-01", "count": 0 }],
    "attendance_rate_by_day": [{ "date": "2026-10-01", "rate": 0.0 }]
  }
}
```
- **Scope is automatic:** instructors/TAs see courses they own, teach a
  session in, or are TA-assigned to; admins see everything.
- **Windowing:** `approval_rate` / `average_attendance_rate` are all-time;
  only `trends` uses `days`.

**Attendance rate, everywhere in this file:** `rejected` check-ins
(blocked fraud) are excluded from every "attendance"/"attended" figure.
Raw counts (`checked_in`, `checked_in_count`) include every row, rejected
ones too. Know which one you're graphing.

### `GET /stats/sessions/{session_id}` — staff who manage the session
```json
{
  "session_id", "session_name", "course_code", "scheduled_start", "status",
  "total_enrolled": 0,
  "checked_in": 0, "checked_in_count": 0,     // same value
  "approved_count": 0, "flagged_count": 0,
  "attendance_rate": 0.0,
  "by_status": { "approved": 0, "flagged": 0, "rejected": 0, "pending": 0, "appealed": 0 },
  "average_risk_score": 0.0,
  "average_distance_meters": 0.0,       // null if no distances
  "average_checkin_time_minutes": 0.0,  // null if no check-ins
  "risk_distribution": { "low": 0, "medium": 0, "high": 0 },
  "checkin_timeline": [{ "minute": 0, "count": 0 }]   // 5-minute buckets from checkin_opens_at
}
```
`risk_distribution` uses the spec's **three** buckets: low < 0.3, medium
< 0.5, high ≥ 0.5. Individual check-ins carry the **four**-band
`risk_level` (LOW / MEDIUM / HIGH / CRITICAL, where CRITICAL ≥ 0.7 =
auto-rejected). So "high" here means HIGH + CRITICAL.

### `GET /stats/courses/{course_id}` — instructor/admin who owns the course
```json
{
  "course_id", "course_code", "course_name",
  "total_sessions": 0, "total_enrolled": 0,
  "overall_attendance_rate": 0.0, "average_attendance_rate": 0.0,  // same value
  "flagged_checkins": 0,
  "sessions": [{ "session_id", "name", "date", "attendance_rate": 0.0, "checked_in": 0 }],
  "student_attendance": [{ "student_id", "student_name", "sessions_attended": 0, "attendance_rate": 0.0, "average_risk_score": 0.0 }],
  "low_attendance_alerts": [{ "student_id", "student_name", "attendance_rate": 0.0, "sessions_missed": 0 }]
}
```
- `start_date`/`end_date` (optional) filter which check-ins count toward the
  per-session breakdown.
- `low_attendance_alerts` uses a **0.75** attendance-rate threshold. That's
  our own default (the spec doesn't give one); ask if you need it
  configurable.

### `GET /stats/students/{student_id}` — instructor (of one of the student's courses) or admin
```json
{
  "student_id", "student_name", "student_email",
  "total_enrolled_courses": 0, "total_sessions": 0, "attended_sessions": 0, "attendance_rate": 0.0,
  "courses": [{ "course_id", "course_code", "attendance_rate": 0.0, "sessions_attended": 0, "total_sessions": 0, "average_risk_score": 0.0 }],
  "recent_sessions": [...], "recent_checkins": [...]   // same content, last 10 check-ins
}
```
Each recent item: `{ "session_name", "course_code", "checked_in_at", "status" }`.

**Not in stats:** check-ins rejected for being **outside Singapore** (`403`)
create **no check-in row**, so they never appear in `/stats/*` or exports.
They're only visible through the audit log (`checkin_rejected_geo`,
`security_violation`) and metrics (`checkin_rejected_geo_total`).

---

## 2. Export (`/api/v1/export/*`)

Both endpoints accept `?format=csv` (default) or `?format=json`. Every
call writes a `data_exported` audit entry (user, IP, record count).

### `GET /export/attendance/{course_id}?format=csv|json`
- **Who:** admin; the course's assigned instructor; or an instructor who
  owns at least one session in it. This is stricter than elsewhere: an
  unrelated instructor gets `403` even for an unassigned course, to avoid
  exposing student data.
- **Filters:** optional `start_date` / `end_date`.
- **`format=csv`:** a download (`Content-Disposition: attachment`) with
  columns `student_id, student_name, student_email, session_date,
  session_name, status, checked_in_at, risk_score`.
- **`format=json`:** a flat array of the same rows.

### `GET /export/session/{session_id}?format=csv|json`
Same "manages this session" check as other session-scoped endpoints.
- **`format=csv`:** same columns, one session's rows.
- **`format=json`:** an **object**, not an array:
  ```json
  { "session_id", "session_name",
    "summary": { "total_enrolled": 0, "checked_in_count": 0, "attendance_rate": 0.0,
                 "approved_count": 0, "flagged_count": 0, "average_risk_score": 0.0 },
    "records": [ /* same rows as the course export */ ] }
  ```

**CSV safety:** text cells starting with `= + - @` (or a tab or carriage
return) are prefixed with `'`, so spreadsheets show them as text instead of
running them as formulas. Example: `'=HYPERLINK(...)`. JSON values are
unchanged. Names and other free text are HTML-escaped when stored
(`&lt;`, `&quot;`), so render them as text.

---

## 3. Audit (`/api/v1/audit/*`) — **admin only**

### `GET /audit/`
Query: `user_id`, `action`, `resource_type`, `resource_id`, `success` (bool),
`start_date`, `end_date`, `limit` (≤ 1000, default 100), `offset`. →
paginated:
```json
{ "items": [{ "id", "user_id", "user_email", "action", "resource_type",
  "resource_id", "ip_address", "user_agent", "device_id", "details": {},
  "success": true, "timestamp": "..." }], "total", "limit", "offset" }
```
**Actions you'll see:**
- **Auth/users:** `login_success`, `login_failed`, `logout`, `account_locked`,
  `user_created`, `user_updated`, `user_deletion_requested`, `face_enrolled`
- **Check-ins:** `checkin_attempted`, `checkin_approved`, `checkin_flagged`,
  `checkin_rejected`, `checkin_rejected_geo`, `checkin_appealed`,
  `checkin_reviewed`
- **Admin data:** `session_created/updated/deleted`,
  `enrollment_added/removed`, `device_registered/updated/removed`,
  `course_created/updated/deleted`, `data_exported`, `retention_sweep_run`
- **Security:** `security_violation`

Useful `details` fields:

| Action | `details` |
|---|---|
| `checkin_approved` / `_flagged` / `_rejected` | `risk_score`, **`risk_level`** (LOW/MEDIUM/HIGH/CRITICAL), `status` |
| `security_violation` | **`violation_type`**: `account_lockout`, `outside_singapore`, `geo_out_of_bounds`, `liveness_failed`, `face_match_failed`, `replay_suspected`, `impossible_travel`, `gps_spoof_suspected`, `rapid_succession` |
| `checkin_rejected_geo` | `reason` (`ip`/`gps`/`gps_and_ip`), `gps_in_singapore`, `ip_country` (no coordinates) |
| `account_locked` | `failed_attempts`, `lockout_minutes` |
| `login_failed` | `email`, or `reason: "account_locked"` |
| `retention_sweep_run` | `users_anonymized`, `checkins_anonymized`, `trigger: "scheduled"` (hourly, no user) |

- **Append-only, enforced by the database.** No row can be edited or
  deleted, even with SQL, so it's safe as a permanent activity feed. Don't
  build anything that modifies it.
- **`ip_address`** = the client's first `X-Forwarded-For` address, or the
  connection address.

### `GET /audit/summary`
Query: `days` (1–365, default 30).
```json
{ "period_days": 30, "total_logs": 0, "success_count": 0, "failed_count": 0,
  "by_action": { "login_success": 0, "checkin_attempted": 0, "...": 0 } }
```
`by_action` gives a ready-made breakdown (e.g. `security_violation` count
for a security overview).

---

## 4. Prometheus metrics (`GET /metrics`)

**Root level, not under `/api/v1`**: `http://<backend-host>:8000/metrics`,
matching `module4-observability/prometheus.yml`. Standard Prometheus text
format. The names are literal; ask before relying on a rename.

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `http_request_duration_seconds` | Histogram | `method`, `path`, `status_code` | Request latency |
| `checkin_attempts_total` | Counter | — | Every `POST /checkins/` (including rejected ones) |
| `checkin_success_total` | Counter | — | Check-ins resolved `approved` |
| `checkins_flagged_total` | Counter | — | Check-ins resolved `flagged` |
| `risk_score` | Histogram | — | Risk score distribution (0.1 buckets) |
| `login_failed_total` | Counter | — | Failed logins, **including** attempts blocked by a lockout |
| `account_lockouts_total` | Counter | — | Accounts locked after 10 consecutive failures |
| `checkin_rejected_geo_total` | Counter | `reason` = `ip`/`gps`/`gps_and_ip` | Check-ins refused as outside Singapore |
| `security_violations_total` | Counter | `violation_type` (as in the audit table) | Every `security_violation` event |

Labelled series only appear after their first occurrence; treat "no data"
as 0 (`or vector(0)`).

```promql
sum by (violation_type) (increase(security_violations_total[1h]))   # suspicious activity
increase(account_lockouts_total[1h])                                 # brute-force attempts
sum(increase(checkin_rejected_geo_total[1h])) / sum(increase(checkin_attempts_total[1h]))
```

**Alert ideas** (Module 4 design deck): a high flagged ratio
(`checkins_flagged_total` / `checkin_attempts_total`), and many failed logins
(`login_failed_total`, `account_lockouts_total`).

If your dashboard is Grafana panels on Prometheus, this section is all you
need. Sections 1–3 are for a custom app calling the REST API (the Streamlit
dashboard).

**Health:** `GET /health` (root level) → `200 healthy`, `200 degraded`
(Redis down) or `503 unhealthy` (database down), with per-component
`database`/`redis` fields. The backend container's Docker healthcheck uses
it, and the dashboard container waits for it.
