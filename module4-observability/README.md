# Module 4 — Observability & Instructor Portal

The instructor-facing half of SAIV: a **Streamlit portal** for staff (port 8501) and the
**Prometheus + Grafana** monitoring stack (ports 9090 / 3001), plus the OpenTelemetry collector.

```
Browser ──► Streamlit portal (8501) ──REST + JWT──► Backend (8000) ──► PostgreSQL
                    │                                   │ /metrics
                    └──PromQL──► Prometheus (9090) ◄────┘
                                      │
                            Grafana (3001) dashboards + alerts
```

The portal reads everything **through the backend API** (never the database directly), so
the backend's role checks apply to every screen.

## Run it

```bash
docker compose up -d --build
python module4-observability/scripts/seed_demo_data.py   # optional: demo accounts + data
```

| What | URL | Login |
|---|---|---|
| Instructor portal | http://localhost:8501 | a TA / instructor / admin account |
| Grafana | http://localhost:3001 | `admin` / `admin` |
| Prometheus | http://localhost:9090 | none |

`seed_demo_data.py` creates these **local test accounts** (password `SaivDemo2026!` for all):
`admin@saiv.demo`, `instructor@saiv.demo`, `ta@saiv.demo`, plus 12 students
(`wei.ling.tan@e.ntu.edu.sg`, …) in course **SC3099** with a closed session, a live session and a
scheduled one, and a realistic mix of approved / flagged / rejected check-ins. Re-running it
adds the next week's sessions.

**Preview mode:** set `DEMO_MODE: "true"` for the `dashboard` service in `docker-compose.yml`
to get an "Explore with sample data" button on the sign-in page (works without a backend).

## Portal pages

| Page | TA | Instructor | Admin | What it does |
|---|:-:|:-:|:-:|---|
| Today | ✓ | ✓ | ✓ | Needs-review count (top-left), today's sessions with live check-in counts, 7-day trends |
| Review queue | ✓ | ✓ | ✓ | Flagged and appealed check-ins, appeals then highest risk first, reasons in plain words, approve / reject with a note |
| Sessions | view | ✓ | ✓ | Create; activate / close / cancel; live attendance, outcome and risk charts, every check-in; per-session export |
| Courses | | ✓ | ✓ | Attendance per session and per student; students under 75% |
| Students | | ✓ | ✓ | One student's attendance across your courses and recent check-ins |
| Exports | session | ✓ | ✓ | CSV (opens in Excel), JSON or PDF, with a course column and optional absent students |
| Accounts | | student/TA | any role | Create one account or import a CSV; enrol students/TAs in a course; remove from a course |
| Audit log | | | ✓ | Filter the append-only log, security-events view, CSV/JSON export |
| System health | | | ✓ | Key Prometheus numbers (flagged rate, failed sign-ins, lockouts, p95, 5xx) + link to Grafana |

Live parts (Today, the open session, System health, new-items notice on the review queue)
refresh every **30 s** without reloading the page; switch off with **Live updates** in the
sidebar.

**Account creation:** admins use `POST /admin/users/bulk` (admin-only in the backend).
Instructors use `POST /auth/register`, which the course spec makes public for every role, so
the instructor → student/TA limit is applied in the portal. CSV columns:
`email, full_name, role, password` (template downloadable on the page).

**Security notes:** tokens live only in Streamlit's server-side session (never in the browser
or URL) and are renewed automatically; sign-out revokes them on the backend. Names and notes
are shown as plain text. CSV exports guard against spreadsheet formula injection. Python
tracebacks are hidden from users.

## Grafana dashboards (folder **SAIV**)

- **SAIV · Attendance & Security** (home dashboard): check-in outcomes, flagged rate, risk
  score bands, failed sign-ins and lockouts, out-of-Singapore rejections, suspicious activity
  by type, and the active-alerts list.
- **SAIV · System Health**: backend / face service / Prometheus up, requests per second,
  p50/p95/p99 latency, 4xx/5xx rates, memory, and face-service panels.

## Alerts (`alert_rules.yml`, evaluated by Prometheus)

| Alert | Fires when |
|---|---|
| `HighFlaggedRate` | over 30% of check-in attempts flagged in 15 min (at least 5 attempts), for 2 min |
| `ManyFailedLogins` | 20+ failed sign-ins in 10 min |
| `BackendDown` | Prometheus can't scrape the backend for 1 min |

They show in Prometheus → *Alerts* and in Grafana's *Active alerts* panel. No email/Slack
contact point is configured.

## Face service metrics (for Module 3)

Prometheus already scrapes `face-recognition:8001/metrics`; the target shows **down** until that
route exists. The System Health panels expect:

| Metric | Type | Labels |
|---|---|---|
| `face_requests_total` | Counter | `endpoint`, `status` |
| `face_request_duration_seconds` | Histogram | `endpoint` |
| `face_verify_total` | Counter | `result` = `match` / `no_match` |
| `liveness_checks_total` | Counter | `result` = `pass` / `fail` |
| `face_enroll_total` | Counter | — |

## OpenTelemetry collector

Receives OTLP on 4317 (gRPC) / 4318 (HTTP) and logs traces with the `debug` exporter; metrics
are re-exposed on 8889. No service sends OTLP data yet; the config only had to be fixed so the
container starts (the old `logging` exporter no longer exists).

## Tests

```bash
docker compose exec dashboard python tests/smoke_test_pages.py
```

Signs in as admin, instructor and TA (seeded accounts), opens every page each role can see,
picks the seeded course/student/session, opens a session and prepares its export, and checks
preview mode. Prints `OK`/`FAIL` per page.

## Known issue (backend)

Assigned TAs are enrolled in their course (that is how the backend scopes TA access), and the
backend's stats and exports count every enrolment as a student. A course with an assigned TA
therefore shows one extra "student" (at 0% attendance) in its numbers and exports.

## Files

```
app/main.py          entry point: sign-in or role-based navigation
app/api.py           all backend + Prometheus calls (token renewal, readable errors)
app/auth.py          sign-in/out, role permissions, course scope
app/ui.py            shared layout, colours, charts, labels
app/exports.py       CSV / JSON / PDF builders
app/demo.py          sample data for preview mode
app/views/*.py       one file per page
.streamlit/config.toml   theme and server settings
grafana/provisioning/    data source, dashboard provider, dashboard JSON
prometheus.yml, alert_rules.yml, otel-collector-config.yml
scripts/seed_demo_data.py, tests/smoke_test_pages.py
```
