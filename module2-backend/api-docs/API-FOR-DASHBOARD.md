# Module 2 Backend API — For Module 4 (Data Analytics Dashboard)

Read [API-CONVENTIONS.md](API-CONVENTIONS.md) first (auth, error format,
pagination). This covers everything your module needs: the `/stats/*`
analytics endpoints, `/export/*` data export, `/audit/*` compliance
logging, and `/metrics` for Prometheus/Grafana.

All endpoints below require **instructor, ta, or admin** — nothing here is
student-accessible, and most narrow further per-endpoint (noted below).

---

## 1. Stats (`/api/v1/stats/*`)

**Read this before you build against field names**: every one of these
four endpoints has fields that exist under **two different names for the
same value** — one matching the written project spec's examples, one
matching what the actual graded test suite asserts. Both are populated in
every response on purpose, not a bug — pick whichever name reads better in
your code, they're always equal.

### `GET /stats/overview` — instructor/ta/admin
Query: `course_id` (optional — omit for your full scope), `days` (1–365,
default 7, controls the trend window only).

```json
{
  "total_sessions": 0, "active_sessions": 0, "total_courses": 0, "total_students": 0,
  "today_checkins": 0, "flagged_pending": 0, "approval_rate": 0.0,

  "total_checkins_today": 0,        // == today_checkins
  "total_checkins_week": 0,
  "average_attendance_rate": 0.0,
  "flagged_pending_review": 0,      // == flagged_pending
  "average_risk_score": 0.0,
  "high_risk_checkins_today": 0,
  "trends": {
    "checkins_by_day": [{ "date": "2026-08-20", "count": 0 }],
    "attendance_rate_by_day": [{ "date": "2026-08-20", "rate": 0.0 }]
  }
}
```
Scope is automatic: an instructor/ta sees only courses they own, teach a
session in, or are TA-assigned to (via an active enrollment) — admin sees
everything. `approval_rate`/`average_attendance_rate` are computed over
**all-time** check-ins, not just the `days` window — only `trends` is
windowed.

**Attendance rate definition, everywhere in this file**: a `rejected`
check-in (caught spoofing/GPS fraud) is excluded from every
"attendance"/"attended" calculation — it represents a blocked fraud
attempt, not genuine attendance. Raw counts (anything literally named
`checked_in`/`checked_in_count`) count every row regardless of status,
including rejected ones. Know which one you're graphing.

### `GET /stats/sessions/{session_id}` — instructor/ta/admin who manages this session
```json
{
  "session_id", "session_name", "course_code", "scheduled_start", "status",
  "total_enrolled": 0,
  "checked_in": 0, "checked_in_count": 0,     // same value, two names
  "approved_count": 0, "flagged_count": 0,
  "attendance_rate": 0.0,
  "by_status": { "approved": 0, "flagged": 0, "rejected": 0, "pending": 0, "appealed": 0 },
  "average_risk_score": 0.0,
  "average_distance_meters": 0.0,   // null if no checkins have a distance recorded
  "average_checkin_time_minutes": 0.0,  // null if no checkins
  "risk_distribution": { "low": 0, "medium": 0, "high": 0 },   // low <0.3, medium <0.5, high >=0.5
  "checkin_timeline": [{ "minute": 0, "count": 0 }]  // 5-minute buckets from checkin_opens_at
}
```
Good source for a single-session dashboard widget (attendance funnel, risk
histogram, arrival-time timeline).

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
Optional `start_date`/`end_date` query params filter which check-ins count
toward the per-session breakdown. `low_attendance_alerts` uses a **0.75
attendance-rate threshold** — this is our own reasoned default (no spec
value exists for it), flag it to us if your dashboard design needs a
different/configurable threshold.

### `GET /stats/students/{student_id}` — instructor/admin (instructor only if this student is enrolled in a course they teach)
```json
{
  "student_id", "student_name", "student_email",
  "total_enrolled_courses": 0, "total_sessions": 0, "attended_sessions": 0, "attendance_rate": 0.0,
  "courses": [{ "course_id", "course_code", "attendance_rate": 0.0, "sessions_attended": 0, "total_sessions": 0, "average_risk_score": 0.0 }],
  "recent_sessions": [...], "recent_checkins": [...]   // identical content, two names, last 10 checkins
}
```
Each recent item: `{ "session_name", "course_code", "checked_in_at", "status" }`.

---

## 2. Export (`/api/v1/export/*`)

Both endpoints accept `?format=csv` (default) or `?format=json`.

### `GET /export/attendance/{course_id}?format=csv|json`
Requires: admin, the course's exact assigned instructor, or an instructor
who owns at least one session under it — **note this is stricter than the
general "unassigned course = any instructor" leniency used elsewhere in
this API** (a deliberate fix for a real PII-disclosure bug — see
`KNOWN-ISSUES.md` if you need the history). Optional `start_date`/
`end_date` filter which check-ins are included.

- `format=csv` → a downloadable file, `Content-Disposition: attachment`,
  columns: `student_id, student_name, student_email, session_date,
  session_name, status, checked_in_at, risk_score`.
- `format=json` → a **flat array** of the same row shape (not wrapped in
  an envelope).

### `GET /export/session/{session_id}?format=csv|json`
Requires the same "manages this session" check as everything else
session-scoped.

- `format=csv` → same columns as above, one session's rows.
- `format=json` → **not** a flat array — an object:
```json
{
  "session_id", "session_name",
  "summary": { "total_enrolled": 0, "checked_in_count": 0, "attendance_rate": 0.0,
               "approved_count": 0, "flagged_count": 0, "average_risk_score": 0.0 },
  "records": [ /* same row shape as course export */ ]
}
```
This shape isn't in the original written spec at all (it only says
"returns a downloadable file") — it was built to match the one hidden test
that actually exercises this endpoint's JSON mode, so treat this as the
real contract.

Both endpoints log a `data_exported` audit entry (see below) every time
they're called, including your IP and the record count — useful if your
dashboard needs to show "who exported what, when" itself.

---

## 3. Audit (`/api/v1/audit/*`) — **admin only**, both endpoints

### `GET /audit/`
Query: `user_id`, `action`, `resource_type`, `resource_id`, `success`
(bool), `start_date`, `end_date`, `limit` (≤1000, default 100), `offset`.
→ paginated:
```json
{ "items": [{ "id", "user_id", "user_email", "action", "resource_type",
  "resource_id", "ip_address", "user_agent", "device_id", "details": {},
  "success": true, "timestamp": "..." }], "total", "limit", "offset" }
```
`action` values you'll see include (not exhaustive):
`login_success`/`login_failed`/`logout`, `user_created`/`user_updated`,
`checkin_attempted`/`checkin_approved`/`checkin_flagged`/
`checkin_rejected`/`checkin_appealed`/`checkin_reviewed`,
`session_created`/`updated`/`deleted`, `enrollment_added`/`removed`,
`device_registered`/`updated`/`removed`, `face_enrolled`,
`course_created`/`updated`/`deleted`, `data_exported`,
`retention_sweep_run`, `security_violation`. This table is append-only —
no row is ever edited or removed, so it's safe to treat as a permanent
event log for any "activity feed" style widget.

### `GET /audit/summary`
Query: `days` (1–365, default 30).
```json
{ "period_days": 30, "total_logs": 0, "success_count": 0, "failed_count": 0,
  "by_action": { "login_success": 0, "checkin_attempted": 0, "...": 0 } }
```
Good for a compliance/security-overview widget — `by_action` gives you a
ready-made breakdown without paginating through raw log rows yourself.

---

## 4. Prometheus metrics (`GET /metrics`)

**Root-level, not under `/api/v1`** — `http://<backend-host>:8000/metrics`
directly, matching `module4-observability/prometheus.yml`'s scrape config
if that's already how your side is wired up. Standard Prometheus text
exposition format, not JSON.

Exact metric names (don't rename on your end without checking with us —
these are the literal names Grafana panels would query via PromQL):

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `http_request_duration_seconds` | Histogram | `method`, `path`, `status_code` | Every request's latency |
| `checkin_attempts_total` | Counter | — | Every `POST /checkins/` call |
| `checkin_success_total` | Counter | — | Check-ins that resolved `approved` |
| `checkins_flagged_total` | Counter | — | Check-ins that resolved `flagged` |
| `login_failed_total` | Counter | — | Failed login attempts |
| `risk_score` | Histogram | — | Distribution of computed risk scores, buckets at 0.1 increments |

If your dashboard is built as Grafana panels against Prometheus rather
than a custom app calling our REST endpoints directly, this is the only
section of this file you need — everything above (`/stats`, `/export`,
`/audit`) is for a custom analytics app/API layer instead, use whichever
matches your actual architecture.
