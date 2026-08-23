# Backend (Module 2) — Implementation Plan

This is your starting point for picking up work on the Backend API. It's a distilled
roadmap, not a replacement for the authoritative specs — when in doubt, the docs below
win over anything summarized here.

## Authoritative specs (read these, this file just orients you around them)

- [`../docs/API-SPECIFICATION.md`](../docs/API-SPECIFICATION.md) — every endpoint, request/response shape, status codes
- [`../docs/SECURITY-REQUIREMENTS.md`](../docs/SECURITY-REQUIREMENTS.md) — auth, rate limits, risk weights (authoritative source of truth for these numbers)
- [`../docs/recommended_design/DATABASE-SCHEMA.md`](../docs/recommended_design/DATABASE-SCHEMA.md) — all 8 tables
- [`../docs/recommended_design/INTEGRATION-GUIDE.md`](../docs/recommended_design/INTEGRATION-GUIDE.md) — how the 4 modules call each other
- [`../tests/public/`](../tests/public/) — the actual graded contract; when a doc and a test disagree, the test wins
- [`../tests/_http_fixtures.py`](../tests/_http_fixtures.py) — shows exactly how tests construct requests; useful for edge cases the spec doesn't spell out

## Role in the system

Backend is the only module that talks to PostgreSQL and to the Face Recognition
service. Frontend and Dashboard only ever talk to you. Every business rule (who's
allowed to do what, is this check-in legitimate, is this session open) is enforced
here — never trust the frontend to have already validated something.

## Project structure

```
app/
  main.py                 # creates the FastAPI app, mounts routers, middleware
  core/
    config.py             # typed Settings (pydantic-settings) reading env vars
    security.py            # bcrypt hash/verify, JWT encode/decode
    deps.py                 # get_db, get_current_user, require_role("admin")
  db/
    base.py                  # SQLAlchemy engine, session factory, declarative Base
    models/                   # user.py, course.py, session.py, checkin.py, device.py,
                               # risk_signal.py, audit_log.py, enrollment.py
  schemas/                  # Pydantic request/response shapes, one file per resource
  routers/                  # auth.py, users.py, courses.py, sessions.py, checkins.py,
                             # stats.py, devices.py, enrollments.py, audit.py, export.py, admin.py
  services/                  # business logic kept OUT of routers:
                              # geofencing.py, risk_scoring.py, face_client.py, audit.py
alembic/                   # migrations, versioned from day 1
```

Routers stay thin: check auth → call a service function → return. Business logic
(risk scoring, geofencing math, calls to Module 3) lives in `services/` so it's
testable and editable in one place.

## Build order (unblock-critical-path first)

Derived from the test fixtures' own dependency chain: `register/login` →
`test_course` (admin) → `test_session` (instructor creates, **admin** activates via
`PATCH /admin/sessions/{id}/status`) → `test_enrollment` (admin) → `test_device`
(student) → check-ins. Build in this order so each phase unblocks the next, and
unblocks your teammates as early as possible.

| # | Phase | Unblocks |
|---|---|---|
| 1 | Skeleton: folders, config, DB connection, Alembic baseline, confirm `docker-compose up` boots clean | Teammates can point env vars at `localhost:8000` |
| 2 | Auth (`register`/`login`/`refresh`) + `/users/me` + JWT/RBAC dependency + bcrypt | Every other endpoint and every test fixture |
| 3 | Admin endpoints (bulk create, activate/deactivate, session status override, admin enrollment) | Test data setup; Module 3/4 teammates creating test users |
| 4 | Courses, Sessions, Enrollments | Frontend's pre-checkin flow; Dashboard's course/session management |
| 5 | Devices (register/list/delete) | Check-in payload requirements |
| 6 | Check-ins (geofencing + risk scoring + defensive calls to Face Service) | End-to-end flow; gives Module 3 a real consumer to test against |
| 7 | Stats, audit log retrieval, export, rate-limit hardening, retention job | Dashboard's analytics views; hidden-test hardening |

**Resilience note for phase 6:** wrap every call to the Face Recognition service in
try/except with a graceful fallback (see `INTEGRATION-GUIDE.md`'s pattern — on
timeout/error, proceed with `liveness_passed: None, liveness_score: 0.0` rather than
crashing). This means your check-in endpoint keeps working even if Module 3 isn't
ready yet or is mid-crash during their own dev — you are not blocked by them.

**Sequencing note:** phase 3's admin endpoints aren't fully independent of phase 4 —
`PATCH /admin/sessions/{id}/status` needs the `sessions` table, `POST
/admin/enrollments/` needs `courses`/`enrollments`. Define all 8 SQLAlchemy models
(from `DATABASE-SCHEMA.md`) during phase 1's skeleton/Alembic baseline, then build the
routers on top of them phase-by-phase — that keeps phase 3 unblocked without
reordering anything.

## Suggested calendar timeline

Anchored to the actual project calendar: today (2026-08-23) is the last day of Week 2,
so Week 3 starts tomorrow and Week 12 (deadline) is 10 weeks out. This compresses the
Briefing's own Week 1–2 "foundation" targets into the start of Week 3, but the 7
phases above only add up to roughly 9–13 focused dev-days, so there's slack to absorb
that.

| Week | Backend focus | Phases | Target |
|---|---|---|---|
| 3 | Skeleton + all 8 DB models/Alembic + Auth/JWT/RBAC | 1 + 2 | `docker-compose up` boots clean; register/login/`/users/me` working |
| 4 | Admin endpoints + Courses/Sessions/Enrollments | 3 + 4 | Test-data setup endpoints work; unblocks Module 3/4 teammates creating test users |
| 5 | Devices + Check-ins core (geofencing, defensive Face Service calls) | 5 + start 6 | Basic check-in flow works even before Module 3's service is ready |
| 6 | Finish Check-ins, integrate with real Face Recognition as Module 3 comes online | finish 6 | End-to-end check-in flow; gives Module 3 a real consumer to test against |
| 7 | Stats, audit log retrieval, export, rate-limit hardening, retention job | 7 | All 90 public tests should be passable by end of this week |
| 8 | Buffer + support Frontend PWA integration | — | Fix whatever Frontend's integration surfaces |
| 9 | Support Dashboard integration | — | Dashboard needs stats/audit/export, already done by week 7 — mostly bugfixing |
| 10 | Performance & privacy hardening | — | DB indexes, fix N+1s, concurrent request handling, verify no raw images anywhere |
| 11 | Hidden-test hardening | — | GPS spoofing detection, replay attack prevention, 100-concurrent stress test |
| 12 | Presentation & demo | — | — |

Of the 40 hidden-test points, roughly 27 are backend-owned (Advanced Security 12,
Privacy Audit 8, Stress Testing 7) and specifically land in weeks 10–11 — that's why
phases 1–7 are front-loaded into weeks 3–7 rather than spread thinner across the whole
semester.

**Calendar conflicts to plan around:** Week 7, Friday 9:30–10:20am is the Individual
Quiz (same week phase 7 wraps up — budget for it if you're taking the "Backend API"
topic). Week 7 also carries the early-stage peer review (5%) and Week 12 the
final-stage one (15%); start a contribution log now rather than reconstructing one
later.

## Cheat sheet — parameters that must match `SECURITY-REQUIREMENTS.md` exactly

| Parameter | Value |
|---|---|
| Bcrypt cost factor | ≥ 10 |
| JWT algorithm | HS256 |
| Access token TTL | 1 hour |
| Refresh token TTL | 7 days |
| Login rate limit | 60/hour per IP |
| API rate limit | 1000/hour per user |
| Check-in rate limit | 10/minute per user |
| Registration rate limit | 10/hour per IP |
| Default risk threshold | 0.5 |
| Liveness pass threshold | 0.6 |
| Face match pass threshold | 0.7 |
| Default geofence radius | 100m |
| Risk signal weights | Liveness 25%, Face match 25%, Device 20%, Network 15%, Geolocation 15% |
| Risk levels | LOW <0.3, MEDIUM 0.3–0.5, HIGH 0.5–0.7, CRITICAL ≥0.7 |
| PII / check-in retention | 30 days (`scheduled_deletion_at`) |

## Common pitfalls (from the course briefing — these are explicitly graded)

- **Never store raw face images** — only the SHA-256 hash (`face_embedding_hash`), and only in-memory processing.
- **Never store plaintext passwords** — bcrypt hash only.
- **Sessions must be `active` before check-ins work** — a session starts as `scheduled`; someone (instructor, or admin via the override endpoint) has to transition it.
- **Implement the `/admin/*` endpoints early** — the entire test suite's setup depends on them, not just the "Observability" test category.
- **Watch for N+1 queries** — use eager loading (`joinedload`/`selectinload`) for anything that lists check-ins/sessions with related user data; this is directly tested under Performance (5 pts) and Stress Testing (7 hidden pts).
- **`audit_logs` has no `updated_at`** — never write code that updates a log row, only inserts.
- **401 vs 403** — invalid/missing/expired token → 401; valid token but wrong role → 403. Don't rely on the frontend hiding buttons as your only access control.

## Gotchas confirmed against tests/specs

These four were checked against `tests/conftest.py`, `tests/_http_fixtures.py`, and the
docs on 2026-08-23. Not contradictions — just details easy to miss when skimming the
plan instead of the source docs.

- **Ignore `app/main.py`'s inline TODO comments.** They're a stale generic skeleton
  (`GET/PATCH /auth/me`, `POST /auth/logout`, `GET /users`, `DELETE /users/{id}`) that
  don't match `API-SPECIFICATION.md` (which has `GET/PUT /users/me`, `GET /users/`,
  `PATCH /users/{user_id}`, and no logout endpoint). Build from the spec/this plan, not
  those comments — delete them once routers land so nobody codes to the wrong shape.
- **Course schema must accept `require_device_binding` and `require_face_recognition`**
  even though the example JSON for `POST /courses/` in `API-SPECIFICATION.md` doesn't
  show them. They're real `courses` columns (`DATABASE-SCHEMA.md`), and
  `tests/conftest.py`'s `test_course` fixture sends `require_device_binding: true` on
  every course it creates. FastAPI ignores unknown fields by default so nothing breaks
  without this, but model them properly since they're genuine columns other modules may
  read.
- **Check-in status has a hard override the risk-threshold table doesn't spell out**:
  regardless of `risk_score` vs `risk_threshold`, `liveness_failed` OR
  `distance_from_venue_meters > 2 × geofence_radius_meters` forces `rejected`. Don't
  implement this as a pure `risk_score < threshold` comparison in
  `services/risk_scoring.py` / the check-in router — the two hard-fail conditions win
  regardless of score.
- **Prefer calling Face Service's `POST /risk/assess`** over re-deriving the 5-signal
  weighted formula locally. `INTEGRATION-GUIDE.md`'s sample code shows the backend
  computing a simplified score itself (liveness + distance + device only), but
  `API-SPECIFICATION.md` documents a full Face Service endpoint that already implements
  the complete weighted formula and returns `signal_breakdown`. Call it with the same
  try/except-and-degrade pattern used for the liveness call (see phase 6's resilience
  note above) so a Face Service outage doesn't take down check-ins.

## Local dev workflow

```bash
# Fast iteration loop: run only infra in Docker, run the API locally
docker-compose up -d postgres redis

# From module2-backend/, with a venv active:
uvicorn app.main:app --reload --port 8000

# Once you have a slice of endpoints working, validate against the real suite:
cd ..
export TEST_BACKEND_URL=http://localhost:8000
export TEST_FACE_URL=http://localhost:8001
python3 -m pytest tests/public/ -v
```

Rebuilding the Docker image on every change is slow — reserve `docker-compose up -d
backend` (full container) for checking the containerized build actually works, not
for your everyday edit-test loop.

## Required environment variables (backend)

```
DATABASE_URL=postgresql://saiv:saiv_password@localhost:5434/saiv   # or postgres:5432 inside compose
REDIS_URL=redis://localhost:6380                                    # or redis:6379 inside compose
SECRET_KEY=<32+ char random string>
FACE_SERVICE_URL=http://localhost:8001                               # or http://face-recognition:8001 inside compose
```

## Definition of done, per phase

A phase isn't "done" until: the relevant `tests/public/` file passes locally against
your running service, the endpoints are visible and correctly documented at
`/docs`, and (once merged) the containerized `docker-compose up` build still boots
clean.
