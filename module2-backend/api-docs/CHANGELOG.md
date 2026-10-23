# Module 2 Backend — Changelog

What changed in the backend, and why, newest first. **For what you need to
do, see the checklist: [CHANGES-2026-10-01.md](CHANGES-2026-10-01.md).**
For how each endpoint behaves now, see the API docs
([conventions](API-CONVENTIONS.md), [frontend](API-FOR-FRONTEND.md),
[face recognition](API-FOR-FACE-RECOGNITION.md),
[dashboard](API-FOR-DASHBOARD.md)). They describe the current behaviour;
this file only explains the changes. Checklist tasks the other modules have
finished are under [Completed team tasks](#completed-team-tasks).

The course's public test suite passes in full (92/92) after every release
below.

---

## 2026-10-23 — `backend/password-change`: liveness retries

**Rebuild needed:** `docker compose up -d --build backend`.

| Area | Before | Now | Why |
|---|---|---|---|
| Liveness challenge feedback | Only after the check-in; a missed step failed the check-in | New `POST /checkins/challenge/{id}/verify {frames}` → `{result, attempts_left, failed_step}`. Up to **3 attempts per session**, a new sequence each time | At ~5 fps a genuine student can miss a blink or a turn; they should get to try again (M1's checklist) |
| Challenge steps not performed | `liveness_failed` → **rejected** | `liveness_challenge_failed` (weight 0) → **flagged** for review, if no later attempt passed | Missing a step isn't proof of fraud. A spoof verdict (`liveness_passed: false`) still rejects, and ends the attempts |
| Skipping the challenge after failing it | — | Counts anyway: after a failed attempt only a verified pass approves; after a spoof verdict the check-in is rejected | Otherwise a plain check-in would bypass the retry limit |
| Verified pass at check-in | — | Only counts with **the same frames** (hash compared, images never stored); the face match then uses those frames | Stops passing the movements with one face and sending another person's photo |
| `POST /checkins/challenge` | — | Also returns `attempts_left`; `409 LIVENESS_ATTEMPTS_EXHAUSTED` when none are left | |

A face-service failure or timeout doesn't use up an attempt. The counter
resets when the session's check-in window ends. A spoof verdict is
reported to the app as `failed` with `attempts_left: 0`, so it can't be
told apart from running out of tries. `failed_step` (from M3's
`steps_passed`) can be switched off with `LIVENESS_FEEDBACK=generic`.

New audit action `liveness_challenge_verified` (one per attempt) and
security-violation types `liveness_spoof`, `challenge_frames_mismatch`.
Until M3 returns `challenge_passed`, every verify answers `unverified` and
check-ins behave as before. M1, M3: see the checklist rows.

**Docs clarified (no behaviour change):** a session without its own
coordinates uses the course's venue, and `PATCH /sessions/{id}` with `null`
coordinates goes back to it (Frontend §4); once a face is enrolled, every
photo check-in is compared with it, and enrolling again replaces it
(Frontend §2). Face enrolment is now a **Should** for M1: the group agreed
students enrol before checking in.

---

## 2026-10-23 — `backend/password-change`: students can change their password

**Rebuild needed:** `docker compose up -d --build backend`.

| Area | Before | Now | Why |
|---|---|---|---|
| Changing a password | Not possible | `POST /users/me/password {current_password, new_password}` → `204` | Accounts created in the dashboard get a default password; students need to set their own (asked for by M1's settings page) |
| Wrong current password | — | `403 PASSWORD_INCORRECT`, and it **counts toward the login lockout** (10 → locked 15 min) | Otherwise a stolen access token would allow unlimited password guesses |
| Many wrong passwords at the same instant | The lock was audited once per parallel request (e.g. 11 `account_locked` + 11 security violations for 20 parallel wrong logins) | Audited once | The lock is now set with a conditional update, so exactly one request sets it |

New audit actions `password_changed` and `password_change_failed` (never
containing the password). New error code `PASSWORD_UNCHANGED` (400). M1:
see the checklist row; M4: the two actions appear in the audit log.

---

## 2026-10-23 — `backend/consent-flag`: consent is enforced (flag)

**Rebuild needed:** `docker compose up -d --build backend`.

| Area | Before | Now | Why |
|---|---|---|---|
| Check-in from a student whose `camera_consent` or `geolocation_consent` isn't `true` | Not checked | Stored, but goes to review: `consent_missing` (weight 0) → at most **flagged** | The briefing requires consent before check-in, and the website now records it (`PUT /users/me`, M1 PR #4) |

`CONSENT_ENFORCEMENT` now defaults to `flag`. Never `reject`: the course's
test fixtures check in without consent and expect `201`. On the normal
website path nothing changes for students: the site saves both consents
before submitting (tested end to end). Check-ins sent some other way
without consent show up in the review queue as "Camera/location consent
not given". No action needed from any module.

---

## 2026-10-23 — `backend/enrollment-and-stats-fixes`

**Rebuild needed:** `docker compose up -d --build backend` (includes a
database migration, which runs automatically).

### Behaviour changes

| Area | Before | Now | Why |
|---|---|---|---|
| Re-adding a removed student (`POST /enrollments/`, `/bulk`, `/admin/enrollments/`) | `400 ALREADY_ENROLLED`; locked out for good | Reactivates the old enrollment (same `id`): `201` / counted as `enrolled` | Removal is a soft delete, so the old row blocked a new one |
| Course/student attendance stats | Counted upcoming and cancelled sessions as missed | Only **held** sessions (`active`/`closed`) count | Rates were too low; alerts fired for classes that hadn't happened |
| Overview `average_attendance_rate` / `attendance_rate_by_day` | Share of check-ins not rejected / approved ÷ day's check-ins | Attended ÷ enrolled, like every other attendance figure | Three different definitions behind one name |
| Check-in with no liveness result (no photo, face service down, no face) | Could be **auto-rejected** a few metres from the venue (local scoring added a distance penalty inside the geofence) | No distance risk inside the geofence; score capped at 0.69 → **flagged**, never auto-rejected unless a hard-reject signal fires | A face-service outage was rejecting genuine students in the room |
| Session created by an admin in an instructor's course | Admin owned it; the course's instructor got `403` starting, closing or reviewing it | Owned by the course's instructor | The session showed up in the instructor's dashboard but every action failed |
| Course and session names / venue names | Stored as typed | HTML-escaped like every other free-text field (existing rows migrated) | XSS consistency |
| Course `code` | Anything | Letters, digits, spaces, `-`, `_`, ≤ 20, else `422` | It's an identifier used in lookups and filenames |
| `GET /checkins/flagged` risk factor `severity` | Always `"medium"` | The signal's real severity | Was hard-coded |
| CSV export filename | Raw session name / course code | Only `[A-Za-z0-9._-]` | A quote or line break broke the download header |
| Deleting an account (after 30 days) | Devices kept name, fingerprint, browser/OS, public key | Devices scrubbed too | "User PII: 30 days after deletion" |
| Singapore-only rule, GPS part | A bounding box, which also covered **Johor Bahru** (city centre, JB Sentral, the checkpoint), Pasir Gudang, Pengerang and **Batam's** north coast | Inside the box **and not on Malaysian or Indonesian land** (OpenStreetMap boundaries, bundled). Singapore's coast, islands and the straits still pass | A check-in from just across the border must get `403 OUTSIDE_SINGAPORE` |

### Robustness (a sweep of ~11,000 hostile requests, then concurrency and outage tests)

| Situation | Before | Now |
|---|---|---|
| NUL character in a path, query or body | `500` | `400 INVALID_INPUT` |
| Number too large for the database (e.g. `offset=10^20`) | `500` | `400 INVALID_INPUT` |
| Name too long once escaped (e.g. 255 × `<`), venue name over 255 | `500` / dropped connection | `422` |
| Password over 4,096 characters | `500` | `422` at sign-up (max 128); a wrong password at login |
| `null` for a required field in `PUT /courses`, `PATCH /sessions`, `PATCH /users/{id}` | `500` | Ignored, like leaving it out |
| Unknown course `instructor_id` | `500` | `404 USER_NOT_FOUND` |
| `geofence_radius_meters` ≤ 0 | Accepted, geofence silently off | `422` |
| The same request twice at the same instant (register, create course, enrol, register device, check in) | Loser got `500` | The normal `400` (same-user device double-tap → `200`) |
| Any unexpected `500` | Also broke the client's **next** request (connection dropped) | Connection stays usable |
| Redis down | Worked, but 8–16 s per request | ~0.2 s (rate limits and logout revocation skipped until it's back) |
| Postgres down | `500` | `503 SERVICE_UNAVAILABLE` + `Retry-After` |
| Face service hung during 100 check-ins | The rest of the API stalled (up to 9.5 s) | Other requests stay fast (check-ins no longer hold a DB connection while waiting) |

---

## 2026-10-22 — `backend/docs-errata` (docs only, no behaviour change)

The docs were checked against the code; these statements were wrong:

| Who | Was | Actually |
|---|---|---|
| M3 | "Front cameras mirror the image" | Frames are **never mirrored**: the student's left is the image's right |
| M1 | "Your preview is probably mirrored" | It isn't; never flip captured frames (a CSS-mirrored preview is fine) |
| M3 | For "no face" on `/face/verify`, send `face_detected: false` | `face_detected` is ignored; `match_passed: false` hard-rejects. Send `match_passed: null` |
| M3 | "A 4xx on `/face/enroll` is handled correctly" | A 4xx becomes `503 FACE_SERVICE_UNAVAILABLE` for the student |
| M1 | A disabled/deleted account gets `403` | Only login does; existing tokens get `401` |
| M1 | A check-in without a photo is always flagged | Only on liveness-required sessions (the default) |
| M1 | `IMAGE_TOO_LARGE` (frame) before `TOO_MANY_FRAMES` | Photo size → frame count → frame sizes |
| M1 | `PUT /courses/{id}` takes every create field | `code` can't be changed |
| M4 | (undocumented) | `flagged_pending` excludes `appealed`; the course-stats date filter applies to every figure |
| M3 | 5 s timeout "strictly enforced" | 5 s per step (connect, start of reply), not a hard cap |
| M1 | Enrolment `503` = "didn't answer within 5 s" | Any face-service failure |

---

## 2026-10-20 — `backend/group-feedback`

- **TAs are no longer counted as students** in `/stats/*`, session
  `total_enrolled` and the export summary. TAs are attached to courses as
  enrollment rows, so a course with a TA showed an extra student at 0%. The
  roster still lists TAs, now with a `role` field and a `?role=` filter.
- **Server-issued liveness challenges and frame bursts.** A fixed "blink"
  can be beaten with a recorded video, so `POST /checkins/challenge` issues a
  random 2-step sequence (`blink` / `turn_left` / `turn_right`, single use,
  ~90 s), and a check-in can carry up to 30 frames. Module 3 reports
  `challenge_passed`. Until it does, challenged check-ins are flagged. The
  single-photo field still works. Enforcement switch
  `LIVENESS_CHALLENGE_ENFORCEMENT` is off.
- **Replay detection covers every frame**, not only the photo.

---

## 2026-10-01 — hand-off baseline (`backend/ntulearn-update`, `internal-hardening`, `deploy-robustness`)

Why: the course re-released its starter with new graded requirements, a
review found security and privacy gaps the hidden tests target, and load
testing showed ~100 simultaneous users broke the backend.

- **Account lockout (graded):** 10 consecutive wrong passwords → locked 15
  min, `429 ACCOUNT_LOCKED` + `Retry-After`, even with the right password.
  Admin `PATCH /admin/users/{id}/activate` unlocks.
- **Singapore-only check-ins (graded):** GPS outside Singapore, or a public
  IP outside Singapore → `403 OUTSIDE_SINGAPORE`, nothing stored (retry
  allowed). Private IPs count as on-campus. Client IP = first
  `X-Forwarded-For` address.
- **Per-IP rate limits raised** to 100,000/hour (graders share one IP).
- **Logout** (`POST /auth/logout`) revokes tokens; **account deletion**
  (`DELETE /users/me`, password required) deactivates now, anonymises
  after 30 days.
- **Face and liveness requirements enforced:** a wrong face on a
  face-required session is rejected (it used to be approved); no result →
  flagged, never auto-approved.
- **Suspicious-activity signals:** `replay_suspected` (rejects),
  `gps_spoof_suspected`, `rapid_succession` (flag), `impossible_travel`,
  `unusual_time`. Coordinates stored at 4 decimals.
- **Privacy:** append-only audit log enforced by the database; automatic
  hourly retention; free text HTML-escaped; CSV formula guard;
  `security_violation` audit events; only hashes of photos and fingerprints.
- **Limits:** images over 10 M base64 chars → `413`; bodies over 15 MB →
  `413`; page size capped at 100.
- **Reliability:** 100+ concurrent users (was stalling with 500s),
  automatic migrations, real `/health`, `X-Request-ID` on every response,
  face-service circuit breaker.
- **Switches built but off:** `CONSENT_ENFORCEMENT`,
  `DEVICE_BINDING_ENFORCEMENT` (they need frontend changes first).

---

## Completed team tasks

Tasks from the [checklist](CHANGES-2026-10-01.md) that the other modules
have finished, newest first. Moved here so the checklist only shows what's
left.

### Module 1 — Frontend: PR #4 (`52112ca`, merged 2026-10-23)

| Was | Task | Done how |
|---|---|---|
| **Must** | Stop baking `192.168.64.4` into the build | Differently from the checklist: a Caddy proxy (`frontend-proxy`) serves the site on `http://localhost:3000` and `https://localhost:3443` (`https://<PUBLIC_HOST>:3443` when `PUBLIC_HOST` is set) and routes `/api/*` to the backend, so the app calls the API on the same origin. `CORS_ORIGINS` updated in the same commit |
| **Must** | Handle `429 ACCOUNT_LOCKED` on login | Shows the wait in minutes from `Retry-After` |
| **Must** | Handle `403 OUTSIDE_SINGAPORE` on check-in | Explains the rule and offers a retry |
| **Should** | Random per-install device fingerprint | `web-<uuid>` in `localStorage`. It's replaced when taken; keeping it is an optional follow-up (see the checklist) |
| **Should** | Send consent to the backend | `PUT /users/me` once the browser grants permission |
| **Should** | Liveness challenge flow | `POST /checkins/challenge`, step prompts with a countdown, frame burst with `challenge_id`; single photo if challenges are unavailable. Frames are not flipped |
| **Should** | Fresh photo every check-in, real GPS accuracy | New capture per attempt; accuracy only sent when the browser reports one |
| **Decide** | Keep or remove the public sign-up page | Removed (accounts are created in the dashboard) |
| Optional | Show CRITICAL as "Critical" | Badge uses `risk_level` |
| Optional | Logout calls `POST /auth/logout` | Tokens revoked, then cleared locally |

### Module 4 — Dashboard: PR #3 (`a604ee8`, merged 2026-10-20)

Grafana provisioning, OTel collector start-up, the new risk signals, session
rules and trailing-slash redirects.

---

## Backend settings

Environment variables on the `backend` service in `docker-compose.yml`.
The defaults are what's running. Invalid values stop the backend at startup.

| Setting | Default | Meaning |
|---|---|---|
| `CONSENT_ENFORCEMENT` | `flag` (was `off` until 2026-10-23) | `off` / `flag` / `reject`. Keep it off `reject` (graded fixtures check in without consent) |
| `DEVICE_BINDING_ENFORCEMENT` | `off` | `off` / `flag` |
| `LIVENESS_CHALLENGE_ENFORCEMENT` | `off` | `off` / `flag` |
| `LIVENESS_CHALLENGE_ACTIONS` | `["blink","turn_left","turn_right"]` | Actions a challenge is drawn from; Module 3 must detect every one |
| `LIVENESS_CHALLENGE_STEPS` / `LIVENESS_CHALLENGE_TTL_SECONDS` | `2` / `90` | Challenge length (1–3) and lifetime |
| `MAX_LIVENESS_FRAMES` / `LIVENESS_TIMEOUT_SECONDS` | `30` / `15` | Frame cap; Module 3 timeout for bursts |
| `REFRESH_TOKEN_ROTATION` | `false` | Single-use refresh tokens |
| `MAX_FAILED_LOGIN_ATTEMPTS` / `ACCOUNT_LOCKOUT_MINUTES` | `10` / `15` | Lockout policy |
| `RATE_LIMIT_LOGIN_PER_HOUR` / `RATE_LIMIT_REGISTRATION_PER_HOUR` | `100000` | Per IP |
| `RATE_LIMIT_CHECKIN_PER_MINUTE` / `RATE_LIMIT_API_PER_HOUR` | `10` / `1000` | Per user |
| `MAX_IMAGE_BASE64_CHARS` / `MAX_REQUEST_BODY_BYTES` | `10000000` / `15000000` | Upload limits |
| `SESSION_START_GRACE_MINUTES` | `5` | How far in the past a new session may start |
| `LOCATION_STORAGE_DECIMALS` | `4` | Stored coordinate precision |
| `PII_RETENTION_DAYS` | `30` | Check-in data and deleted accounts |
| `RETENTION_SWEEP_INTERVAL_MINUTES` | `60` | `0` disables the automatic sweep |
| `CORS_ORIGINS` | `localhost:3000`, `:8501` (compose adds `https://localhost:3443` and the `PUBLIC_HOST` origins) | Allowed browser origins. The student site calls the API through its same-origin proxy, so this only matters for direct calls |

---

## Try it yourself

```bash
API=http://localhost:8000/api/v1
curl -s localhost:8000/health

# Lockout: 10 wrong passwords, then the right one -> 429 + Retry-After
for i in $(seq 1 10); do curl -s -o /dev/null -w "%{http_code} " -X POST $API/auth/login \
  -H 'Content-Type: application/json' -d '{"email":"you@test.edu","password":"wrong"}'; done
curl -i -X POST $API/auth/login -H 'Content-Type: application/json' -d '{"email":"you@test.edu","password":"<correct>"}'

# Singapore rule: a foreign IP -> 403 (needs an active session you're enrolled in)
curl -i -X POST $API/checkins/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'X-Forwarded-For: 8.8.8.8' \
  -d '{"session_id":"<id>","latitude":1.3483,"longitude":103.6831,"location_accuracy_meters":10,"device_fingerprint":"dev1"}'

# Liveness challenge, then check in with it + frames; the same challenge again -> 400 CHALLENGE_INVALID
curl -s -X POST $API/checkins/challenge -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"session_id":"<id>"}'
```

Interactive docs for every endpoint: http://localhost:8000/docs

---

## Merge history

| Merged as | Contents |
|---|---|
| `backend/consent-flag` | 2026-10-23: consent enforced as `flag` |
| `backend/enrollment-and-stats-fixes` | 2026-10-23 release above |
| `backend/docs-errata` (`950af50`) | 2026-10-22 corrections above |
| `backend/group-feedback` (`ffb466c`) | 2026-10-20 release above |
| `backend/deploy-robustness` | Migrations on start, health check, upload limits, future session start, logout, account deletion, `risk_level`, CSV guard, enforcement switches |
| `backend/internal-hardening` (`8813475`) | 100-user concurrency, bcrypt 10, append-only audit, retention, XSS on appeal/review text, `X-Request-ID`, suspicious-activity signals, 4-dp coordinates |
| `backendsmallfixes` (`0bb9bf7`) | Face-service 4xx no longer blocks other students; geolocation sent only with accuracy |
| `backend/ntulearn-update` (`dd017e7`) | Lockout, Singapore rule, `X-Forwarded-For`, admin-only course edit, rate limits, face/liveness enforcement |
