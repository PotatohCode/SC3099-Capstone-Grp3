# Module 2 Backend API — For Module 1 (Frontend)

Read [API-CONVENTIONS.md](API-CONVENTIONS.md) first (auth, error format,
pagination, rate limits) — this file assumes it.

This covers every endpoint your UI is likely to call, across all four
roles (student/instructor/ta/admin), since one frontend serves all of them.
Each entry notes which role(s) can call it.

---

## 1. Auth

### `POST /api/v1/auth/register` — anyone
```json
// Request
{ "email": "a@b.com", "password": "min 8 chars", "full_name": "...", "role": "student" }
```
`role` defaults to `"student"` if omitted; accepts any of the four roles.
**201** → `UserResponse` (see §2). **422** if password < 8 chars or email
malformed. **400 EMAIL_ALREADY_REGISTERED** if the email's taken. **429** if
this IP has registered 300+ times in the last hour.

### `POST /api/v1/auth/login` — anyone
```json
{ "email": "a@b.com", "password": "..." }
```
**200** → `{ "access_token", "refresh_token", "token_type": "bearer", "user": UserResponse }`.
**401 INVALID_CREDENTIALS** wrong email/password. **403 ACCOUNT_DISABLED** if
`is_active=false`. **429** after 60 failed attempts from this IP in an hour.

### `POST /api/v1/auth/refresh` — anyone with a valid refresh token
```json
{ "refresh_token": "..." }
```
**200** → `{ "access_token", "refresh_token", "token_type": "bearer" }`
(no `user` field here, unlike login). **401 INVALID_REFRESH_TOKEN** if
expired/invalid/an access token was passed instead.

---

## 2. My profile (any authenticated role)

### `GET /api/v1/users/me`
→ `UserResponse`:
```json
{ "id", "email", "full_name", "role", "is_active", "camera_consent",
  "geolocation_consent", "face_enrolled", "created_at" }
```
No password field ever appears in any response, anywhere.

### `PUT /api/v1/users/me`
Partial update — only send fields you're changing:
```json
{ "full_name": "...", "camera_consent": true, "geolocation_consent": true }
```
→ **200** updated `UserResponse`. This is how consent gets recorded before
face enrollment or GPS-based check-in — make sure your consent UI actually
calls this, not just a local toggle.

### `POST /api/v1/users/me/face/enroll`
```json
{ "image": "<base64 PNG/JPEG, no data: URL prefix>" }
```
→ **200** `{ "success": true, "message": "...", "face_enrolled": true, "quality_score": 0.0-1.0 }`.
**400 CAMERA_CONSENT_REQUIRED** if `camera_consent` is false — call `PUT
/users/me` first. **400 NO_FACE_DETECTED** if the image has no detectable
face. **503 FACE_SERVICE_UNAVAILABLE** if Module 3 doesn't respond within
5s — **this will happen for the entire duration Module 3 isn't finished**,
build a real retry/error state for it, not just a spinner.

---

## 3. Courses

### `GET /api/v1/courses/` — public, no auth required
Query: `is_active` (default `true`), `semester`, `instructor_id` (only
honored if you're admin or it's your own id), `limit` (≤200, default 50),
`offset`. → paginated `CourseResponse` items (see below). This is
intentionally callable with no `Authorization` header at all for
list/browse views.

### `GET /api/v1/courses/{id}` — any authenticated role
→ single `CourseResponse`:
```json
{ "id", "code", "name", "description", "semester", "instructor_id",
  "instructor_name", "venue_name", "venue_latitude", "venue_longitude",
  "geofence_radius_meters", "require_face_recognition",
  "require_device_binding", "risk_threshold", "is_active", "created_at" }
```
`instructor_id` can be `null` — a course with no assigned owner is normal
in this system (any instructor can manage it until claimed — see
KNOWN-ISSUES.md if you need the reasoning for an admin UI).

### `POST /api/v1/courses/` — **admin only**
```json
{ "code": "CS101", "name": "...", "semester": "2026S1",
  "description": null, "instructor_id": null, "venue_name": null,
  "venue_latitude": null, "venue_longitude": null,
  "geofence_radius_meters": 100.0, "require_face_recognition": false,
  "require_device_binding": true, "risk_threshold": 0.5 }
```
Only `code`/`name`/`semester` are required. **201** → `CourseResponse`.
**400 COURSE_CODE_TAKEN** if `code` isn't unique.

### `PUT /api/v1/courses/{id}` — admin, or the assigned instructor
Same fields as create, all optional (partial update), plus `is_active`.
**403** if you're an instructor who isn't this course's owner.

### `DELETE /api/v1/courses/{id}` — **admin only**
**204**. Soft-delete (`is_active=false`), not a real row delete.

---

## 4. Sessions

### `GET /api/v1/sessions/` — instructor/ta/admin
Query: `status`, `course_id`, `instructor_id`, `start_date`, `end_date`,
`limit` (≤200), `offset`. → paginated `SessionResponse` (see below).

### `GET /api/v1/sessions/active` — any authenticated role
No pagination, plain array. Returns sessions currently `active` **and**
inside their check-in window right now — this is what a student's
"check in now" screen should poll/call, not `/sessions/`.

### `GET /api/v1/sessions/my-sessions` — any authenticated role
Query: `status`, `upcoming` (bool), `limit`. Plain array, role-scoped
automatically: students see sessions for courses they're enrolled in;
instructor/ta see sessions they own or are TA-assigned to; admin sees
everything.

### `GET /api/v1/sessions/{id}` — any authenticated role
→ single `SessionResponse`:
```json
{ "id", "course_id", "course_code", "course_name", "instructor_id",
  "name", "session_type", "description", "status", "scheduled_start",
  "scheduled_end", "checkin_opens_at", "checkin_closes_at",
  "actual_start", "actual_end", "venue_latitude", "venue_longitude",
  "venue_name", "geofence_radius_meters", "require_liveness_check",
  "require_face_match", "risk_threshold", "qr_code_enabled",
  "total_enrolled", "checked_in_count", "created_at" }
```
`session_type` ∈ `lecture|tutorial|lab|exam`. `status` ∈
`scheduled|active|closed|cancelled`. `qr_code_enabled` is currently
**always false** — QR check-in isn't implemented, don't build UI for it yet.

### `POST /api/v1/sessions/` — instructor or admin
```json
{ "course_id": "...", "name": "...", "session_type": "lecture",
  "scheduled_start": "2026-...", "scheduled_end": "2026-...",
  "checkin_opens_at": null, "checkin_closes_at": null,
  "venue_latitude": null, "venue_longitude": null,
  "require_liveness_check": true, "require_face_match": false,
  "risk_threshold": null }
```
If `checkin_opens_at`/`checkin_closes_at` are omitted, they default to 15
min before / 30 min after `scheduled_start`. Caller must own the parent
course (admin, or the assigned instructor — or any instructor if the
course has no owner yet). **201** → `SessionResponse`.

### `PATCH /api/v1/sessions/{id}` — instructor or admin who manages this session
Partial update, any subset of the create fields plus `status`. Setting
`status: "active"` stamps `actual_start`; `status: "closed"` stamps
`actual_end` — this is how your "start/end session" instructor controls
should work, not a separate endpoint.

### `DELETE /api/v1/sessions/{id}` — instructor or admin who manages this session
**204**. **Real delete**, not soft — but **400 SESSION_NOT_DELETABLE**
unless `status == "scheduled"` (never started).

---

## 5. Enrollments

### `GET /api/v1/enrollments/my-enrollments` — student only
Plain array of `{ id, course_id, course_code, course_name, semester, instructor_name, enrolled_at, is_active }`.

### `GET /api/v1/enrollments/course/{course_id}` — instructor/ta/admin who staff this course
→ `{ course_id, course_code, total_enrolled, students: [{ id, student_id, student_email, student_name, enrolled_at, is_active, face_enrolled }] }`
This is your course roster view — `face_enrolled` per student is here so
you can flag who hasn't enrolled their face yet.

### `POST /api/v1/enrollments/` — instructor/admin who owns the course
```json
{ "student_id": "...", "course_id": "..." }
```
**201** → `{ id, student_id, course_id, is_active, enrolled_at }`.
**400 ALREADY_ENROLLED** if a row already exists.

### `POST /api/v1/enrollments/bulk` — instructor/admin who owns the course
```json
{ "course_id": "...", "student_emails": ["a@b.com", ...], "create_accounts": false }
```
If `create_accounts: true`, unknown emails get a brand-new student account
with a random unrecoverable password — **there is no password-reset flow
for these accounts yet**, so don't build a "forgot password" UI expecting
one to exist server-side. **200** →
`{ enrolled, already_enrolled, not_found, created, details: [{email, status}] }`.

### `DELETE /api/v1/enrollments/{id}` — instructor/admin who owns the course
**204**. Soft (`is_active=false`, `dropped_at` stamped).

---

## 6. Devices

### `POST /api/v1/devices/register` (or `POST /api/v1/devices/`, identical — both exist)
```json
{ "device_fingerprint": "...", "device_name": null, "platform": "web",
  "browser": null, "os_version": null, "app_version": null, "public_key": null }
```
`platform` ∈ `ios|android|web|desktop`, optional. **201** if new, **200**
if you're re-registering a fingerprint you already own (updates in place —
check the status code, don't assume 201 always). **400
DEVICE_FINGERPRINT_TAKEN** if it belongs to a different user.

### `GET /api/v1/devices/my-devices` — any authenticated role
Plain array of `DeviceResponse`:
```json
{ "id", "device_fingerprint", "device_name", "platform", "browser",
  "os_version", "app_version", "is_trusted", "trust_score", "is_active",
  "total_checkins", "first_seen_at", "last_seen_at" }
```

### `PATCH /api/v1/devices/{id}` — owner or admin
```json
{ "device_name": "...", "is_active": false, "is_trusted": true }
```
`is_trusted` silently no-ops for a non-admin caller (not rejected, just
ignored) — don't show it as editable in a non-admin UI.

### `DELETE /api/v1/devices/{id}` — owner or admin
**204**. Soft (revokes, doesn't erase history).

---

## 7. Check-ins — the core flow

### `POST /api/v1/checkins/` — **student only**
```json
{ "session_id": "...", "latitude": 1.35, "longitude": 103.68,
  "location_accuracy_meters": 10.0, "device_fingerprint": "...",
  "liveness_challenge_response": null, "qr_code": null }
```
`liveness_challenge_response` (base64 image) is **optional** — omitting it
just means no liveness/face-match signal gets factored in (Module 3 isn't
finished yet, so this currently never runs regardless). `qr_code` is
accepted but never checked (not implemented). Register the device first,
or send a fingerprint that resolves to `device_id: null` in the response.

Validation before it even reaches risk scoring, in order: enrolled in the
course? (**403 NOT_ENROLLED**) → session active? (**400
SESSION_NOT_ACTIVE**) → inside the check-in window? (**400
SESSION_WINDOW_CLOSED**) → already checked in for this session? (**400
ALREADY_CHECKED_IN**). Rate-limited to 10/minute per student.

**201** → full `CheckinResponse`:
```json
{ "id", "session_id", "student_id", "device_id", "status",
  "checked_in_at", "verified_at", "latitude", "longitude",
  "location_accuracy_meters", "distance_from_venue_meters",
  "liveness_passed", "liveness_score", "face_match_passed",
  "face_match_score", "face_embedding_hash", "risk_score",
  "risk_factors": [{"type", "weight"}], "qr_code_verified",
  "reviewed_by_id", "reviewed_at", "review_notes",
  "appeal_reason", "appealed_at" }
```
`status` ∈ `pending|approved|flagged|rejected|appealed`. Build your
post-check-in UI around all three real outcomes (approved/flagged/
rejected), not just success/failure — a `flagged` result is still a
**201**, not an error.

### `GET /api/v1/checkins/my-checkins` — student only
Plain array (not paginated): `{ id, session_id, session_name, course_code, status, checked_in_at, risk_score }`.

### `GET /api/v1/checkins/{id}` — the student who owns it, or instructor/ta/admin who manages the session
→ full `CheckinResponse` (same shape as create).

### `POST /api/v1/checkins/{id}/appeal` — the owning student only
```json
{ "appeal_reason": "..." }
```
Only for `flagged`/`rejected` check-ins, only within 7 days of
`checked_in_at`. **400 ALREADY_APPEALED** / **APPEAL_NOT_ALLOWED** /
**APPEAL_WINDOW_EXPIRED** as appropriate. **200** →
`{ id, status: "appealed", appeal_reason, appealed_at }`.

### `GET /api/v1/checkins/` — instructor/ta/admin
Query: `session_id`, `course_id`, `student_id`, `status`, `min_risk_score`,
`max_risk_score`, `start_date`, `end_date`, `limit` (≤200), `offset`. →
paginated list, scoped automatically to courses/sessions you staff (admin
sees all). Each item: `{ id, session_id, session_name, student_id, student_name, student_email, status, checked_in_at, distance_from_venue_meters, risk_score, liveness_passed }`.

### `GET /api/v1/checkins/session/{session_id}` — instructor/ta/admin who manages this session
Plain array, richer per-item detail including `risk_factors` and
`device_trusted`. Use this for a single-session "who checked in" screen.

### `GET /api/v1/checkins/flagged` — instructor/ta/admin
Query: `course_id`, `session_id`, `limit` (≤200), `offset`. → **paginated**
(unlike the two above's plain arrays — check the field, this one really is
`{items, total, limit, offset}`). Includes `appealed` status rows too, not
just `flagged`. This is your review-queue screen.

### `POST /api/v1/checkins/{id}/review` — instructor/ta/admin who manages the session
```json
{ "status": "approved", "review_notes": "..." }
```
`status` must be `"approved"` or `"rejected"`. Only callable on
`flagged`/`appealed` check-ins. **200** →
`{ id, status, reviewed_by_id, reviewed_at, review_notes }`.

---

## 8. Admin-only setup endpoints

Useful if you're building an admin panel (not just for automated tests,
though that's their original purpose):

| Endpoint | Body | Notes |
|---|---|---|
| `PATCH /api/v1/admin/users/{id}/deactivate` | — | → `{id, email, is_active: false, message}` |
| `PATCH /api/v1/admin/users/{id}/activate` | — | → `{id, email, is_active: true, message}` |
| `POST /api/v1/admin/users/bulk` | `{"users": [{"email","password","full_name","role"}]}` | **201** → `{created, failed, users: [...], errors: [{email, error}]}` |
| `PATCH /api/v1/admin/sessions/{id}/status` | `{"status": "active"}` | Same status values as session `PATCH`, but bypasses the ownership check `PATCH /sessions/{id}` requires |
| `POST /api/v1/admin/enrollments/` | `{"student_id","course_id"}` | Same as `POST /enrollments/` but bypasses course-ownership |
| `POST /api/v1/admin/retention/run` | — | Runs the PII retention sweep (30-day check-in/user anonymization) on demand — not something an end-user UI needs, but useful if you're building an admin "data management" screen |

Also: `GET /api/v1/users/` (admin, filters `role`/`is_active`/`search`,
paginated) and `GET /api/v1/users/{id}` / `PATCH /api/v1/users/{id}` (admin,
or self, or an instructor viewing their own enrolled student) — for a user
management screen.

---

## Things worth designing around up front

- **Module 3 (Face Recognition) is not built yet.** Every liveness/face
  endpoint call degrades gracefully (returns `null`-ish fields or a 503,
  never crashes) — but that means face enrollment and face-matched
  check-ins can't functionally succeed today. Build the UI, expect it to
  visibly not-quite-work until that team ships, and don't hardcode an
  assumption that `503 FACE_SERVICE_UNAVAILABLE` is rare.
- **`GET /courses/` is the one endpoint safe to call with zero auth state**
  — good for a landing/browse page before login.
- **A `flagged` check-in is a normal, expected outcome**, not an error
  state — the risk-scoring pipeline is designed to catch spoofing attempts,
  so build real UI for it (appeal flow, "pending review" messaging), not
  just a generic error toast.
