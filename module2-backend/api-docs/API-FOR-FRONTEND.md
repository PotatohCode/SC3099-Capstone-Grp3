# Module 2 Backend API — For Module 1 (Frontend)

Read [API-CONVENTIONS.md](API-CONVENTIONS.md) first (auth, error format,
pagination, rate limits). **Your tasks:** the Module 1 table in
[CHANGES-2026-10-01.md](CHANGES-2026-10-01.md). **Why things changed:**
[CHANGELOG.md](CHANGELOG.md).

This covers every endpoint your UI is likely to call, across all four roles
(student/instructor/ta/admin), since one frontend serves all of them. Each
entry notes who can call it. Last updated 2026-10-23.

---

## 1. Auth

### `POST /api/v1/auth/register` — anyone
```json
{ "email": "a@b.com", "password": "min 8 chars", "full_name": "...", "role": "student" }
```
`role` defaults to `"student"`; any of the four roles is accepted.
**201** → `UserResponse` (§2). **422** password < 8 or > 128 chars, or
malformed email.
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

### `POST /api/v1/auth/logout` — anyone
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
when the student grants camera/location permission, **before submitting the
check-in**. It's required for face enrolment, and a check-in from a student
without both consents goes to review (`consent_missing`, see §7).

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
| `503 FACE_SERVICE_UNAVAILABLE` | Module 3 failed: it didn't answer in time (~5 s), returned an error, or is temporarily skipped after earlier failures (30 s). Let the user retry |

Without an enrolled face, check-ins on face-required sessions are always
`flagged`, so an enrolment step matters.

### `POST /api/v1/users/me/password` — any authenticated role
```json
{ "current_password": "<current password>", "new_password": "<new password>" }
```
→ **204** (no body). The new password works at the next login. Tokens
already issued stay valid until they expire, so there's no need to log the
user out.

| Response | Meaning |
|---|---|
| `422` | `new_password` under 8 or over 128 characters (same rules as sign-up), or a field missing |
| `400 PASSWORD_UNCHANGED` | `new_password` is the same as the current one |
| `403 PASSWORD_INCORRECT` | Wrong `current_password`. Deliberately not 401, so your 401 → refresh → logout logic doesn't fire |
| `429 ACCOUNT_LOCKED` + `Retry-After` | Too many wrong passwords. **Wrong passwords here count toward the same lockout as login** (10 → locked 15 min, login included). Show the same message as on the login page |

Useful for accounts created by an admin with a default password: a
settings page where the student sets their own.

### `DELETE /api/v1/users/me` — any authenticated role (right to deletion)
```json
{ "password": "<current password>" }
```
→ **202** `{ "message": "...", "scheduled_deletion_at": "..." }`. The account
is deactivated **immediately** (its tokens stop working and login returns
`403 ACCOUNT_DISABLED`), and personal data, including registered devices,
is anonymised after 30 days.
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
- `code`: letters, digits, spaces, `-` and `_` only, up to 20 characters
  (else `422`). **400 COURSE_CODE_TAKEN** if it exists.
- `name` / `venue_name` are stored HTML-escaped.
- `geofence_radius_meters` must be > 0 (`422`).
- An `instructor_id` that doesn't exist → **404 USER_NOT_FOUND**.
- `risk_threshold` may be 0–1, but scores ≥ 0.7 are always rejected (above
  0.7 nothing gets flagged).

### `PUT /api/v1/courses/{id}` — **admin only**
Same fields as create, all optional, plus `is_active`, **except `code`**,
which can't be changed (a `code` in the body is silently ignored). `null`
for a required field is ignored; for an optional one it clears it. **403
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
window, **for every course** (not just the student's).

### `GET /api/v1/sessions/my-sessions` — any authenticated role
Query: `status`, `upcoming` (bool), `limit`. Plain array, scoped by role:
students see their enrolled courses' sessions; instructors/TAs see sessions
they own plus every session of the courses they're assigned to as TA;
admins see all.
**`status=active` does not check the check-in window.** A session an
instructor forgot to close stays `active` after its window ends, and a
check-in then gets `400 SESSION_WINDOW_CLOSED`. For a student's "check in
now" list, call `my-sessions?status=active` and keep only sessions where
`checkin_opens_at <= now <= checkin_closes_at` (UTC).

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
(QR check-in isn't implemented). `total_enrolled` counts **students only**;
assigned TAs aren't included.

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
- **Owner (`instructor_id`)** = the creator, except when an **admin** creates
  a session in a course with an assigned instructor: then **that instructor**
  owns it, so they can start, close, review and see its stats. In a course
  with no assigned instructor, the admin stays the owner.
- `name` / `venue_name` are stored HTML-escaped; `geofence_radius_meters`
  must be > 0.

### `PATCH /api/v1/sessions/{id}` — instructor or admin who manages it
Partial update plus `status`. `status: "active"` stamps `actual_start`;
`"closed"` stamps `actual_end`. Use these for "start/end session" controls.
`null` for a required field is ignored.

### `DELETE /api/v1/sessions/{id}` — instructor or admin who manages it
**204**, a real delete, but **400 SESSION_NOT_DELETABLE** unless
`status == "scheduled"`.

---

## 5. Enrollments

### `GET /api/v1/enrollments/my-enrollments` — student only
Plain array of `{ id, course_id, course_code, course_name, semester, instructor_name, enrolled_at, is_active }`.

### `GET /api/v1/enrollments/course/{course_id}` — instructor/ta/admin who staff the course
→ `{ course_id, course_code, total_enrolled, students: [{ id, student_id, student_email, student_name, role, enrolled_at, is_active, face_enrolled }] }`.
`face_enrolled` lets you show who still needs to enrol their face.
**Assigned TAs are on this list too** (that's how TA access works), with
`role: "ta"`. Add `?role=student` (or `?role=ta`) to get only one kind;
`total_enrolled` counts what's returned. Optional `?search=` filters by name
or email. `?is_active=false` lists removed enrollments instead (default
`true`).

### `POST /api/v1/enrollments/` — instructor/admin who owns the course
`{ "student_id": "...", "course_id": "..." }` → **201**. **400 ALREADY_ENROLLED**
only if the student is currently enrolled. Re-adding a **removed** student
reactivates their old enrollment (same `id`, new `enrolled_at`) and
returns **201**. Bulk enrolment and `POST /admin/enrollments/` behave the
same way.

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

**Recommended: on `DEVICE_FINGERPRINT_TAKEN`, keep the ID rather than generating a new one.**
It means another student already registered this browser, which is the
shared-phone case the backend is meant to see. Carry on with the check-in:
it scores `device_unknown`, and if two students use the same ID within
10 minutes the second check-in goes to review (`rapid_succession`). A new
ID would hide that.

### `GET /api/v1/devices/my-devices` — any authenticated role
Plain array of `{ id, device_fingerprint, device_name, platform, browser, os_version, app_version, is_trusted, trust_score, is_active, total_checkins, first_seen_at, last_seen_at }`.

### `PATCH /api/v1/devices/{id}` — owner or admin
`{ "device_name": "...", "is_active": false, "is_trusted": true }`.
`is_trusted` is silently ignored for non-admins.

### `DELETE /api/v1/devices/{id}` — owner or admin
**204**. Soft (revoked, history kept).

---

## 7. Check-ins — the core flow

### `POST /api/v1/checkins/challenge` — **student only**
Get a random liveness challenge for the next check-in.
```json
// request
{ "session_id": "..." }
// 201
{ "challenge_id": "...", "session_id": "...", "sequence": ["blink", "turn_left"],
  "expires_at": "2026-10-20T04:01:30", "max_frames": 30, "attempts_left": 3 }
```
- `sequence`: 2 steps by default, from `blink`, `turn_left`, `turn_right`.
  Left/right are the **student's own** left/right, so prompt them that way.
  Send the frames exactly as captured: **never flip them**. If you mirror
  the on-screen preview (selfie style), do it in CSS only; that doesn't
  affect what `drawImage` captures. Never the same step twice in a row.
  More actions may be added later: show a generic prompt for one you don't
  recognise.
- **Expires after ~90 s and works once.** Fetch it right before capturing.
  `expires_at` is **UTC** with no `Z` (like every timestamp; see
  API-CONVENTIONS), so `2026-10-20T04:01:30` is 12:01:30 in Singapore.
- Checks the session first: `404 SESSION_NOT_FOUND`, `403 NOT_ENROLLED`,
  `400 SESSION_NOT_ACTIVE` / `SESSION_WINDOW_CLOSED`. It does **not** check
  "already checked in" or the Singapore rule; those still come from the
  check-in itself. More than 30 per minute → `429 RATE_LIMITED`.
- `attempts_left`: liveness attempts this student has left **for this
  session** (3 per session), including the one this challenge is for.
- `409 LIVENESS_ATTEMPTS_EXHAUSTED`: no attempts left. Don't retry; submit
  the check-in without a challenge. It goes to review.
- `503 CHALLENGE_UNAVAILABLE`: challenges are down. Check in with a single
  photo instead.

**Capture:** show each step in order and record ~5 frames per second, about
8 per step (≈16 frames for 2 steps), as small JPEGs (≈640 px wide), base64
without the `data:` prefix, oldest first. At most `max_frames` frames, each
under 10,000,000 base64 characters, and the whole request under 15 MB.

### `POST /api/v1/checkins/challenge/{challenge_id}/verify` — **student only**
Checks the burst **before** the check-in, so the student can retry if the
steps weren't caught. Optional: a check-in can still send a challenge
without verifying it first (checked at check-in, no retry).
```jsonc
// request: the burst for this challenge (same format as the check-in's frames)
{ "frames": ["<base64 frame>", "..."] }
// 200
{ "result": "passed" | "failed" | "unverified", "attempts_left": 2, "failed_step": "turn_left" }
```

| `result` | What to do |
|---|---|
| `passed` | Submit `POST /checkins/` with this `challenge_id` and **the exact same frames** |
| `failed`, `attempts_left` > 0 | "We couldn't confirm the movements, try again": get a **new** challenge (new sequence) and capture again |
| `failed`, `attempts_left` = 0 | Stop retrying. Submit the check-in with this `challenge_id` and frames; it goes to review |
| `unverified` | The face service couldn't check it. **No attempt used.** Submit the check-in with this `challenge_id` and frames (it's checked again there; if still unverified, it goes to review) |

- **Same frames at check-in.** A pass only counts for the burst it was
  verified on (compared by hash; images aren't stored). Different frames,
  or a photo only → the pass doesn't count and the check-in goes to review.
  With a verified pass, the face match uses the middle frame of that burst,
  not a separate photo.
- `failed_step` (optional): the first step that wasn't detected, e.g.
  `"turn_left"`, when the face service reports per-step results. May be
  `null`, and may be switched off server-side, so **don't rely on it**: fall
  back to the generic message.
- `attempts_left` is `null` if the backend couldn't read it (rare).
- **Each challenge is verified once.** Verifying it again, an expired one,
  or another student's → `400 CHALLENGE_INVALID`. No attempts left →
  `409 LIVENESS_ATTEMPTS_EXHAUSTED`. Frames: `422` if empty,
  `413 TOO_MANY_FRAMES` / `IMAGE_TOO_LARGE` as at check-in. More than 30
  per minute → `429`.
- **Skipping the challenge doesn't help.** Once a student has failed an
  attempt in a session, only a verified pass can approve their check-in;
  otherwise it's flagged (`liveness_challenge_failed`). Some verdicts end
  the attempts at once (reported as `failed` with `attempts_left: 0`).
- Until Module 3 ships frame checking, every verify answers `unverified`.

### `POST /api/v1/checkins/` — **student only**
```jsonc
{ "session_id": "...", "latitude": 1.35, "longitude": 103.68,
  "location_accuracy_meters": 10.0, "device_fingerprint": "...",
  "liveness_challenge_response": "<base64 photo, optional>",
  "liveness_challenge_frames": ["<base64 frame>", "..."],  // optional: burst for a challenge
  "challenge_id": "...",                                    // optional: from /checkins/challenge
  "challenge_type": null,                                   // optional: label only, e.g. "blink"
  "qr_code": null }
```
- **Two ways to send liveness:** one photo (`liveness_challenge_response`,
  as before), or a challenge burst (`challenge_id` +
  `liveness_challenge_frames`). The photo field keeps working.
- **Challenge outcome:** with a verified challenge (see `/verify` above),
  its result is used. Otherwise the face service checks the frames here.
  Steps not performed → `flagged` for review (`liveness_challenge_failed`),
  never rejected for that alone. Can't confirm the steps → at most
  `flagged` (`liveness_unverified`). Until Module 3 ships frame checking,
  challenged check-ins are flagged.
- `challenge_type` (lowercase letters and `_`) is only a label stored with
  the check-in when you send frames **without** a challenge.
- **Send a fresh photo or burst every time.** If **any** image (the photo or
  any one frame) was used in an earlier check-in by the same student, the
  check-in is rejected (`replay_suspected`).
- **Send full-precision GPS and the real accuracy** from the Geolocation API.
  An accuracy under 1 m is treated as a mocked location
  (`gps_spoof_suspected`, flagged).
- **Singapore-only rule:** the GPS must be in Singapore (its islands and the
  straits count; Johor Bahru, Pengerang and Batam don't), **and** the client
  IP must not be a public IP located outside Singapore. Private/local IPs
  count as on-campus. Otherwise `403 OUTSIDE_SINGAPORE`, nothing is stored,
  and the student can retry (e.g. after turning off a VPN). For testing, use
  NTU (`1.3483, 103.6831`); devtools locations outside Singapore get `403`.
- `qr_code` is accepted but not checked (QR isn't implemented).

**Checks, in order** (the first failure wins):

| Response | Meaning | UI |
|---|---|---|
| `429 RATE_LIMITED` | More than 10 check-ins per minute | Wait and retry |
| `413 IMAGE_TOO_LARGE` | Photo over the size limit | "Photo too large, retake" |
| `413 TOO_MANY_FRAMES` | More than 30 frames | Send fewer frames |
| `413 IMAGE_TOO_LARGE` | Any one frame over the size limit | Retake with smaller frames |
| `404 SESSION_NOT_FOUND` | Unknown session | |
| `403 NOT_ENROLLED` | Not enrolled in the course | |
| `400 SESSION_NOT_ACTIVE` / `SESSION_WINDOW_CLOSED` | Not open right now | |
| `400 ALREADY_CHECKED_IN` | Already has a check-in for this session | Offer appeal if it was rejected |
| `403 CONSENT_REQUIRED` | Only if the backend's consent enforcement is set to `reject` (it's `flag`: missing consent is stored and reviewed, not refused) | Ask for camera + location permission |
| `403 OUTSIDE_SINGAPORE` | GPS outside Singapore (including Johor Bahru and Batam, just across the straits), or a public IP outside Singapore. **Nothing saved, retry allowed** | "Check-in is only available within Singapore. If you're using a VPN, turn it off and try again." |
| `400 CHALLENGE_INVALID` | `challenge_id` unknown, expired, already used, or for another session/student. **Nothing saved** | Get a new challenge and redo the steps |

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
- **A check-in without a liveness result is never auto-rejected** unless a
  hard-reject signal fires (GPS more than 2× the geofence away, or a
  replayed image). "Without a liveness result" means no photo, the face
  service is down, or no face was found. Its score is capped at **0.69**
  (`HIGH`), and on liveness-required sessions (the default) it's always
  `flagged` for review. A missing liveness result counts as full risk, so
  such check-ins score high (~0.68 from an unregistered device).
  Auto-approval needs a photo, and on face-required sessions an enrolled
  face. (On a session with `require_liveness_check: false`, a no-photo
  check-in from an admin-trusted device can score under the threshold and be
  approved.)

**How the outcome is decided:** a hard-reject signal, or a score ≥ 0.7 →
`rejected`; else a score ≥ the session's/course's `risk_threshold` (default
0.5), or a review-only signal → `flagged`; else `approved`. The score is a
base (Module 3's `/risk/assess` when available, otherwise a local formula)
plus the weights below, capped at 1.0.

| `risk_factors` type | Severity | Weight | Effect |
|---|---|---|---|
| `geo_out_of_bounds` | high (1–2× radius) / **critical** (> 2×) | 0.15 | > 2× geofence → **rejected** |
| `geo_accuracy_low` | low | 0.05 | Accuracy worse than 100 m |
| `gps_spoof_suspected` | medium | 0 | Accuracy < 1 m → at most flagged |
| `device_unknown` | medium / low | 0.10 / 0.05 | Unregistered / registered but not trusted |
| `impossible_travel` | high | 0.30 | > 250 km/h from the previous check-in |
| `liveness_failed` | **critical** | 0.25 | The face service judged it a spoof → **rejected** |
| `liveness_challenge_failed` | high | 0 | Challenge steps not detected (and no later attempt passed) → at most flagged |
| `liveness_unverified` | high | 0 | Liveness required but no result → at most flagged |
| `face_match_failed` | **critical** | 0.25 | Face-required session, wrong face → **rejected** |
| `face_match_unverified` | high | 0 | Face required but no comparison → at most flagged |
| `replay_suspected` | **critical** | 0.30 | Re-used photo or frame (same student) → **rejected** |
| `rapid_succession` | high | 0 | Device used by another student < 10 min ago → at most flagged |
| `unusual_time` | low | 0 | > 15 min after start; informational |
| `consent_missing` | medium | 0 | Camera or location consent not `true` on the account → at most flagged (on by default) |
| `device_unbound` | medium | 0 | Only with `DEVICE_BINDING_ENFORCEMENT=flag` |

**Critical = rejects on its own.** `risk_level` bands: `LOW` < 0.3 ≤
`MEDIUM` < 0.5 ≤ `HIGH` < 0.7 ≤ `CRITICAL` (always rejected).

### `GET /api/v1/checkins/my-checkins` — student only
Query: `course_id` (optional), `limit` (default 50, max 100). Plain array: `{ id, session_id, session_name, course_code, status, checked_in_at, risk_score, risk_level }`.

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
is the review queue. Each item's `risk_factors` are `{type, severity,
weight}`, where `severity` ∈ `critical|high|medium|low` (table above).

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

Also, for user and device management screens:
- `GET /api/v1/users/` (admin; filters `role`, `is_active`, `search`;
  paginated); `GET /api/v1/users/{id}` (admin, yourself, or an instructor of
  one of that student's courses); `PATCH /api/v1/users/{id}` (admin;
  `{role, is_active}`, `null` ignored).
- `GET /api/v1/devices/` (admin; filters `user_id`, `is_trusted`,
  `is_active`; paginated). An admin `PATCH /devices/{id} {"is_trusted": true}`
  marks a device trusted.

---

## Things worth designing around

- **The backend address is fixed at build time** (`NEXT_PUBLIC_API_URL`).
  Keep it relative (`/`, through the `frontend-proxy` service), never one
  machine's LAN IP.
- **Flagged/rejected are normal outcomes,** not errors. Build the appeal flow
  and "pending review" messaging.
- **`GET /courses/` and `GET /sessions/active` work without login.**
- **Errors carry an `X-Request-ID` header.** Log it or show it in error
  details so backend issues can be traced.
- **Free text comes back HTML-escaped** (e.g. `&lt;`), including course,
  session and venue names. Render it as text: "R&D Lab" comes back as
  `R&amp;D Lab`. If you want it to display as `&`, unescape it for display
  only (it's still safe as text).
- **A double-tap is safe:** two identical requests at once get one success
  and the normal `400` (e.g. `ALREADY_CHECKED_IN`).
- **The `frontend-proxy` (Caddy) sets `X-Forwarded-For` to the real client
  IP** and replaces any value the browser sent, so it can't be spoofed
  through the site. The backend uses its first address for the Singapore
  rule, rate limits and audit logs. Keep that if you change the proxy, and
  never set the header from browser code.
