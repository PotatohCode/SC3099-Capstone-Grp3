# Module 2 Backend API — For Module 1 (Frontend)

Read [API-CONVENTIONS.md](API-CONVENTIONS.md) first (auth, error format,
pagination, rate limits). For **what changed and what you need to do**, see
[CHANGES-2026-10-01.md](CHANGES-2026-10-01.md) §1 and the Module 1 guide in
§4.

This covers every endpoint your UI is likely to call, across all four roles
(student/instructor/ta/admin), since one frontend serves all of them. Each
entry notes who can call it. Last updated 2026-10-01.

---

## 1. Auth

### `POST /api/v1/auth/register` — anyone
```json
{ "email": "a@b.com", "password": "min 8 chars", "full_name": "...", "role": "student" }
```
`role` defaults to `"student"`; any of the four roles is accepted.
**201** → `UserResponse` (§2). **422** password < 8 chars or malformed email.
**400 EMAIL_ALREADY_REGISTERED**.

### `POST /api/v1/auth/login` — anyone
```json
{ "email": "a@b.com", "password": "..." }
```
**200** → `{ "access_token", "refresh_token", "token_type": "bearer", "user": UserResponse }`.

| Response | Meaning | Show |
|---|---|---|
| `401 INVALID_CREDENTIALS` | Wrong email or password | "Incorrect email or password" |
| `403 ACCOUNT_DISABLED` | Account deactivated or deleted | "This account is disabled" |
| `429 ACCOUNT_LOCKED` + `Retry-After` | 10 consecutive wrong passwords; locked 15 min, **even with the correct password** | "Too many failed sign-in attempts. Locked for N minutes", with `N = ceil(Retry-After / 60)` |

`http-client.ts` already puts `Retry-After` in `error.rateLimit.retryAfterSeconds`.
A `429` from login in practice always means `ACCOUNT_LOCKED`.

### `POST /api/v1/auth/refresh` — anyone with a valid refresh token
```json
{ "refresh_token": "..." }
```
**200** → `{ "access_token", "refresh_token", "token_type": "bearer" }` (no
`user`). **Store the new refresh token.** **401 INVALID_REFRESH_TOKEN** if
expired, revoked, or an access token was sent.

### `POST /api/v1/auth/logout` — anyone (new)
```json
{ "refresh_token": "..." }        // optional; also send Authorization: Bearer <access>
```
Revokes the tokens you send; they get `401` everywhere from then on. Always
**204**, even if they're already invalid. Call it before clearing local
tokens on sign-out.

---

## 2. My profile (any authenticated role)

### `GET /api/v1/users/me`
→ `UserResponse`:
```json
{ "id", "email", "full_name", "role", "is_active", "camera_consent",
  "geolocation_consent", "face_enrolled", "created_at" }
```
No password field appears in any response.

### `PUT /api/v1/users/me`
Partial update; send only what changes:
```json
{ "full_name": "...", "camera_consent": true, "geolocation_consent": true }
```
→ **200** updated `UserResponse`. **This is how consent is recorded.** Call it
when the student grants camera/location permission. Today consent is only
stored in the browser, so the backend sees `false`. This is required for
face enrolment, and later for consent enforcement on check-in.

### `POST /api/v1/users/me/face/enroll`
```json
{ "image": "<base64 PNG/JPEG, no data: URL prefix>" }
```
→ **200** `{ "success": true, "message": "...", "face_enrolled": true, "quality_score": 0.0-1.0 }`.

| Response | Meaning |
|---|---|
| `400 CAMERA_CONSENT_REQUIRED` | `camera_consent` is false; call `PUT /users/me` first |
| `400 NO_FACE_DETECTED` | No usable face in the image |
| `413 IMAGE_TOO_LARGE` | Image over 10,000,000 base64 characters |
| `503 FACE_SERVICE_UNAVAILABLE` | Module 3 didn't answer within 5 s; let the user retry |

Without an enrolled face, check-ins on face-required sessions are always
`flagged`, so an enrolment step matters.

### `DELETE /api/v1/users/me` — new (right to deletion)
```json
{ "password": "<current password>" }
```
→ **202** `{ "message": "...", "scheduled_deletion_at": "..." }`. The account
is deactivated **immediately** (its tokens stop working and login returns
`403 ACCOUNT_DISABLED`), and personal data is anonymised after 30 days.
**403 PASSWORD_INCORRECT** for a wrong password. This is deliberately not
401, so your 401 → refresh → logout logic doesn't fire.

---

## 3. Courses

### `GET /api/v1/courses/` — public, no auth required
Query: `is_active` (default `true`), `semester`, `instructor_id` (honoured
for admin or your own id), `limit` (default 50, max 100), `offset`. →
paginated `CourseResponse` items. Safe to call before login.

### `GET /api/v1/courses/{id}` — any authenticated role
→ `CourseResponse`:
```json
{ "id", "code", "name", "description", "semester", "instructor_id",
  "instructor_name", "venue_name", "venue_latitude", "venue_longitude",
  "geofence_radius_meters", "require_face_recognition",
  "require_device_binding", "risk_threshold", "is_active", "created_at" }
```
`instructor_id` can be `null` (a course with no assigned owner yet; any
instructor can manage it until one is set).

### `POST /api/v1/courses/` — **admin only**
```json
{ "code": "CS101", "name": "...", "semester": "2026S1",
  "description": null, "instructor_id": null, "venue_name": null,
  "venue_latitude": null, "venue_longitude": null,
  "geofence_radius_meters": 100.0, "require_face_recognition": false,
  "require_device_binding": true, "risk_threshold": 0.5 }
```
Only `code`/`name`/`semester` are required. **201** → `CourseResponse`.
**400 COURSE_CODE_TAKEN**. `risk_threshold` may be 0–1, but scores ≥ 0.7 are
always rejected (above 0.7 nothing gets flagged).

### `PUT /api/v1/courses/{id}` — **admin only**
Same fields as create, all optional, plus `is_active`. **403
INSUFFICIENT_PERMISSIONS** for any non-admin, including the course's own
instructor. Show course editing to admins only.

### `DELETE /api/v1/courses/{id}` — **admin only**
**204**. Soft delete (`is_active=false`).

---

## 4. Sessions

### `GET /api/v1/sessions/` — instructor/ta/admin
Query: `status`, `course_id`, `instructor_id`, `start_date`, `end_date`,
`limit` (max 100), `offset`. → paginated `SessionResponse`.

### `GET /api/v1/sessions/active` — public, no auth required
Plain array of sessions currently `active` **and** inside their check-in
window. Use this (or `my-sessions`) for a "check in now" screen.

### `GET /api/v1/sessions/my-sessions` — any authenticated role
Query: `status`, `upcoming` (bool), `limit`. Plain array, scoped by role:
students see their enrolled courses' sessions; instructors/TAs see sessions
they own or staff; admins see all.

### `GET /api/v1/sessions/{id}` — any authenticated role
→ `SessionResponse`:
```json
{ "id", "course_id", "course_code", "course_name", "instructor_id",
  "name", "session_type", "description", "status", "scheduled_start",
  "scheduled_end", "checkin_opens_at", "checkin_closes_at",
  "actual_start", "actual_end", "venue_latitude", "venue_longitude",
  "venue_name", "geofence_radius_meters", "require_liveness_check",
  "require_face_match", "risk_threshold", "qr_code_enabled",
  "total_enrolled", "checked_in_count", "created_at" }
```
`session_type` ∈ `lecture|tutorial|lab|exam`; `status` ∈
`scheduled|active|closed|cancelled`. `qr_code_enabled` is always `false`
(QR check-in isn't implemented).

### `POST /api/v1/sessions/` — instructor or admin
```json
{ "course_id": "...", "name": "...", "session_type": "lecture",
  "scheduled_start": "2026-...Z", "scheduled_end": "2026-...Z",
  "checkin_opens_at": null, "checkin_closes_at": null,
  "venue_latitude": null, "venue_longitude": null,
  "require_liveness_check": true, "require_face_match": false,
  "risk_threshold": null }
```
- Omitted `checkin_opens_at`/`checkin_closes_at` default to 15 min before /
  30 min after `scheduled_start`.
- **`scheduled_start` may not be more than 5 minutes in the past** → `400
  INVALID_SCHEDULE`. End must be after start, and closes after opens.
- The caller must manage the parent course. **201** → `SessionResponse`.

### `PATCH /api/v1/sessions/{id}` — instructor or admin who manages it
Partial update plus `status`. `status: "active"` stamps `actual_start`;
`"closed"` stamps `actual_end`. Use these for "start/end session" controls.

### `DELETE /api/v1/sessions/{id}` — instructor or admin who manages it
**204**, a real delete, but **400 SESSION_NOT_DELETABLE** unless
`status == "scheduled"`.

---

## 5. Enrollments

### `GET /api/v1/enrollments/my-enrollments` — student only
Plain array of `{ id, course_id, course_code, course_name, semester, instructor_name, enrolled_at, is_active }`.

### `GET /api/v1/enrollments/course/{course_id}` — instructor/ta/admin who staff the course
→ `{ course_id, course_code, total_enrolled, students: [{ id, student_id, student_email, student_name, enrolled_at, is_active, face_enrolled }] }`.
`face_enrolled` lets you show who still needs to enrol their face.

### `POST /api/v1/enrollments/` — instructor/admin who owns the course
`{ "student_id": "...", "course_id": "..." }` → **201**. **400 ALREADY_ENROLLED**.

### `POST /api/v1/enrollments/bulk` — instructor/admin who owns the course
```json
{ "course_id": "...", "student_emails": ["a@b.com"], "create_accounts": false }
```
With `create_accounts: true`, unknown emails get a new student account with
a random, unrecoverable password (there's no password-reset flow). **200** →
`{ enrolled, already_enrolled, not_found, created, details: [{email, status}] }`.

### `DELETE /api/v1/enrollments/{id}` — instructor/admin who owns the course
**204**. Soft (`is_active=false`).

---

## 6. Devices

### `POST /api/v1/devices/register` (or `POST /api/v1/devices/`, identical)
```json
{ "device_fingerprint": "...", "device_name": null, "platform": "web",
  "browser": null, "os_version": null, "app_version": null, "public_key": null }
```
`device_fingerprint` is at most 64 characters. `platform` ∈
`ios|android|web|desktop`. **201** new; **200** re-registering your own
fingerprint (updated in place). **400 DEVICE_FINGERPRINT_TAKEN** if another
user owns it.

**Use a random per-install fingerprint** (e.g. `crypto.randomUUID()` in
`localStorage`). A fingerprint built from browser traits is shared by
everyone with the same phone model. They then can't register devices, and
two of them checking in within 10 minutes are flagged as `rapid_succession`.

### `GET /api/v1/devices/my-devices` — any authenticated role
Plain array of `{ id, device_fingerprint, device_name, platform, browser, os_version, app_version, is_trusted, trust_score, is_active, total_checkins, first_seen_at, last_seen_at }`.

### `PATCH /api/v1/devices/{id}` — owner or admin
`{ "device_name": "...", "is_active": false, "is_trusted": true }`.
`is_trusted` is silently ignored for non-admins.

### `DELETE /api/v1/devices/{id}` — owner or admin
**204**. Soft (revoked, history kept).

---

## 7. Check-ins — the core flow

### `POST /api/v1/checkins/` — **student only**
```json
{ "session_id": "...", "latitude": 1.35, "longitude": 103.68,
  "location_accuracy_meters": 10.0, "device_fingerprint": "...",
  "liveness_challenge_response": "<base64 photo, optional>", "qr_code": null }
```
- **Send a fresh photo every time.** A photo the same student already used is
  rejected (`replay_suspected`).
- **Send full-precision GPS and the real accuracy** from the Geolocation API.
  An accuracy under 1 m is treated as a mocked location
  (`gps_spoof_suspected`, flagged).
- `qr_code` is accepted but not checked (QR isn't implemented).

**Checks, in order** (the first failure wins):

| Response | Meaning | UI |
|---|---|---|
| `429 RATE_LIMITED` | More than 10 check-ins per minute | Wait and retry |
| `413 IMAGE_TOO_LARGE` | Photo over the size limit | "Photo too large, retake" |
| `404 SESSION_NOT_FOUND` | Unknown session | |
| `403 NOT_ENROLLED` | Not enrolled in the course | |
| `400 SESSION_NOT_ACTIVE` / `SESSION_WINDOW_CLOSED` | Not open right now | |
| `400 ALREADY_CHECKED_IN` | Already has a check-in for this session | Offer appeal if it was rejected |
| `403 CONSENT_REQUIRED` | Only if the backend's consent enforcement is set to `reject` (off by default) | Ask for camera + location permission |
| `403 OUTSIDE_SINGAPORE` | GPS or public IP outside Singapore. **Nothing saved, retry allowed** | "Check-in is only available within Singapore. If you're using a VPN, turn it off and try again." |

**201** → `CheckinResponse`:
```json
{ "id", "session_id", "student_id", "device_id", "status",
  "checked_in_at", "verified_at", "latitude", "longitude",
  "location_accuracy_meters", "distance_from_venue_meters",
  "liveness_passed", "liveness_score", "face_match_passed",
  "face_match_score", "face_embedding_hash", "risk_score", "risk_level",
  "risk_factors": [{"type", "weight"}], "qr_code_verified",
  "reviewed_by_id", "reviewed_at", "review_notes",
  "appeal_reason", "appealed_at" }
```
- **A 201 is not "approved". Check `status`** (`approved` | `flagged` |
  `rejected`). Flagged and rejected are normal outcomes. Show them clearly
  and offer **Appeal**.
- `risk_level` ∈ `LOW|MEDIUM|HIGH|CRITICAL`. Use it for the badge; CRITICAL
  is a rejection.
- `latitude`/`longitude` come back rounded to 4 decimals (privacy rule).
- **A check-in without a photo is always `flagged`** (~0.68 risk), because a
  missing liveness result counts as full risk. Auto-approval needs a photo,
  and on face-required sessions an enrolled face.
- The full list of `risk_factors` types and what each means is in
  [CHANGES §5.3](CHANGES-2026-10-01.md#53-risk-factor-types).

### `GET /api/v1/checkins/my-checkins` — student only
Plain array: `{ id, session_id, session_name, course_code, status, checked_in_at, risk_score, risk_level }`.

### `GET /api/v1/checkins/{id}` — the owning student, or staff who manage the session
→ full `CheckinResponse`.

### `POST /api/v1/checkins/{id}/appeal` — the owning student only
`{ "appeal_reason": "..." }`. Only for `flagged`/`rejected`, within 7 days,
once. **400 ALREADY_APPEALED** / **APPEAL_NOT_ALLOWED** /
**APPEAL_WINDOW_EXPIRED**. **200** → `{ id, status: "appealed", appeal_reason, appealed_at }`.
The reason is HTML-escaped when stored.

### `GET /api/v1/checkins/` — instructor/ta/admin
Query: `session_id`, `course_id`, `student_id`, `status`, `min_risk_score`,
`max_risk_score`, `start_date`, `end_date`, `limit` (max 100), `offset`. →
paginated, scoped to what you staff (admin sees all). Items:
`{ id, session_id, session_name, student_id, student_name, student_email, status, checked_in_at, distance_from_venue_meters, risk_score, risk_level, liveness_passed }`.

### `GET /api/v1/checkins/session/{session_id}` — staff who manage the session
Plain array with `risk_factors`, `risk_level` and `device_trusted`. For a
"who checked in" screen.

### `GET /api/v1/checkins/flagged` — instructor/ta/admin
Query: `course_id`, `session_id`, `limit` (max 100), `offset`. →
**paginated** `{items, total, limit, offset}`. Includes `appealed` rows. This
is the review queue.

### `POST /api/v1/checkins/{id}/review` — staff who manage the session
`{ "status": "approved" | "rejected", "review_notes": "..." }`. Only on
`flagged`/`appealed`. **200** → `{ id, status, reviewed_by_id, reviewed_at, review_notes }`.

---

## 8. Admin endpoints

| Endpoint | Body | Notes |
|---|---|---|
| `PATCH /api/v1/admin/users/{id}/deactivate` | — | → `{id, email, is_active: false, message}` |
| `PATCH /api/v1/admin/users/{id}/activate` | — | Also **clears a login lockout** and **cancels a pending account deletion** |
| `DELETE /api/v1/users/{id}` | — | Admin account deletion (no password); **202** |
| `POST /api/v1/admin/users/bulk` | `{"users": [{"email","password","full_name","role"}]}` | **201** → `{created, failed, users, errors}` |
| `PATCH /api/v1/admin/sessions/{id}/status` | `{"status": "active"}` | Bypasses session ownership |
| `POST /api/v1/admin/enrollments/` | `{"student_id","course_id"}` | Bypasses course ownership |
| `POST /api/v1/admin/retention/run` | — | Runs the retention sweep now (it also runs automatically every hour) |

Also `GET /api/v1/users/` (admin; filters `role`, `is_active`, `search`;
paginated), and `GET` / `PATCH /api/v1/users/{id}`, for a user management
screen.

---

## Things worth designing around

- **The backend address must not be baked to one machine's LAN IP.**
  `docker-compose.yml` currently builds the frontend with
  `NEXT_PUBLIC_API_URL=http://192.168.64.4:8000`, which breaks the site on
  every other machine. See CHANGES §4, Module 1 guide.
- **Flagged/rejected are normal outcomes,** not errors. Build the appeal flow
  and "pending review" messaging.
- **`GET /courses/` and `GET /sessions/active` work without login.**
- **Errors carry an `X-Request-ID` header.** Log it or show it in error
  details so backend issues can be traced.
- **Free text comes back HTML-escaped** (e.g. `&lt;`). Render it as text.
