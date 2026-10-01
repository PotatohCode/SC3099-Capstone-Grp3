# Module 2 Backend — Shared API Conventions

Read this first, then whichever of these applies to you:

- [API-FOR-FRONTEND.md](API-FOR-FRONTEND.md) — Module 1
- [API-FOR-FACE-RECOGNITION.md](API-FOR-FACE-RECOGNITION.md) — Module 3
- [API-FOR-DASHBOARD.md](API-FOR-DASHBOARD.md) — Module 4

> **What changed, and what each module needs to do:**
> [CHANGES-2026-10-01.md](CHANGES-2026-10-01.md). It's the consolidated
> baseline; where anything here disagrees, that document is newer.

This describes the **implemented behaviour** of the Module 2 backend as of
**2026-10-01**: the course's public test suite passes in full (92/92 points).
Where the written course spec and the implementation differ, this is what's
actually running; the reasons are given in CHANGES-2026-10-01.md.

Interactive docs for every endpoint and schema: `http://localhost:8000/docs`.

---

## Base URL

- Local dev (docker-compose): `http://localhost:8000`
- All endpoints are under `/api/v1` **except** `GET /health`, `GET /` and
  `GET /metrics` (root level, no prefix).

## Authentication

JWT bearer tokens, `HS256`. Get one with `POST /api/v1/auth/register` then
`POST /api/v1/auth/login` (or just `/login` if the account exists).

```
Authorization: Bearer <access_token>
```

- **Access token**: 60 minutes. **Refresh token**: 7 days. Refresh with
  `POST /api/v1/auth/refresh` and `{"refresh_token": "..."}`. There's no
  automatic renewal. Always store the new refresh token returned.
- **Logout**: `POST /api/v1/auth/logout` with the refresh token in the body
  and/or the access token in the header. Revoked tokens get `401`
  everywhere from then on. It always returns `204`.
- Token claims: `sub` (user id), `email`, `role`, `type` (`access` or
  `refresh`), `iat`, `exp`, `jti` (unique id, used for revocation). Don't
  rely on claims beyond what `/users/me` returns.
- **401** = missing, invalid, expired or revoked token. **403** = valid token
  but wrong role or ownership, a disabled/deleted account, or a business
  rule (e.g. `OUTSIDE_SINGAPORE`, `PASSWORD_INCORRECT`). Don't conflate the
  two: only 401 should trigger "refresh token, then log out".

## Roles

`student | instructor | ta | admin`: one global role per user, not per
course. Course/session-level permissions (e.g. "may this instructor manage
*this* course?") are an additional check, documented per endpoint in the
module files.

Registration accepts **any** role, including `admin`. The course briefing
says to ignore role restrictions during registration.

## Error format

Every error response **except 422** looks like:

```json
{ "detail": "Human-readable message", "code": "MACHINE_READABLE_CODE" }
```

**422** (validation failures, e.g. missing field, password under 8
characters, malformed email) keeps FastAPI's default shape:

```json
{ "detail": [ { "type": "...", "loc": [...], "msg": "...", ... } ] }
```

Build error handling on **`code`**, not the `detail` text. Codes you'll see:

| Group | Codes |
|---|---|
| Auth | `INVALID_CREDENTIALS`, `ACCOUNT_LOCKED` (429), `ACCOUNT_DISABLED`, `INVALID_TOKEN`, `INVALID_REFRESH_TOKEN`, `PASSWORD_INCORRECT`, `EMAIL_ALREADY_REGISTERED` |
| Permissions | `INSUFFICIENT_PERMISSIONS`, `NOT_ENROLLED` |
| Not found | `*_NOT_FOUND` (course, session, user, student, device, enrollment, checkin) |
| Check-ins | `ALREADY_CHECKED_IN`, `SESSION_NOT_ACTIVE`, `SESSION_WINDOW_CLOSED`, `OUTSIDE_SINGAPORE`, `CONSENT_REQUIRED` (only if enabled), `ALREADY_APPEALED`, `APPEAL_NOT_ALLOWED`, `APPEAL_WINDOW_EXPIRED`, `REVIEW_NOT_ALLOWED` |
| Sessions/courses | `INVALID_SCHEDULE`, `COURSE_CODE_TAKEN`, `SESSION_NOT_DELETABLE`, `ALREADY_ENROLLED` |
| Devices/face | `DEVICE_FINGERPRINT_TAKEN`, `CAMERA_CONSENT_REQUIRED`, `NO_FACE_DETECTED`, `FACE_SERVICE_UNAVAILABLE` (503) |
| Limits | `RATE_LIMITED` (429), `IMAGE_TOO_LARGE` (413), `REQUEST_TOO_LARGE` (413) |
| Server | `INTERNAL_ERROR` (500; details are logged server-side, never returned) |

## Pagination

Paginated list endpoints return:

```json
{ "items": [...], "total": 123, "limit": 50, "offset": 0 }
```

- `limit` / `offset` are query parameters. Most defaults are 50.
- **Maximum `limit` is 100**. Larger values are **capped, not rejected**:
  you get 100 items and `"limit": 100`. The audit log allows up to 1000.
- **Not every list is paginated.** Some (e.g. `/sessions/active`,
  `/checkins/my-checkins`) return a plain `[...]`. Check each endpoint.

## Rate limiting and lockout

All 429s include a `Retry-After` header (seconds), readable from browser code.

| Limit | Value | Keyed by | Response |
|---|---|---|---|
| Login: consecutive failures on one account | 10, then locked 15 min | account | `429 ACCOUNT_LOCKED`, even with the right password |
| Login failures | 100,000/hour | IP | `429 RATE_LIMITED` (course asked for a high value) |
| Registration | 100,000/hour | IP | `429 RATE_LIMITED` |
| Check-in submission | 10/minute | user | `429 RATE_LIMITED` |
| Everything else | 1000/hour | user | `429 RATE_LIMITED` |

## Request and response details

- **`X-Request-ID`**: every response, including errors, has one. Send your
  own (letters, digits, `. _ -`, up to 64 chars) to trace a request, or quote
  the returned one when reporting a bug.
- **Upload limits**: images over 10,000,000 base64 characters →
  `413 IMAGE_TOO_LARGE`. Any body over 15 MB → `413 REQUEST_TOO_LARGE`.
- **Health**: `GET /health` → `200 {"status":"healthy","database":"ok","redis":"ok", ...}`;
  `"degraded"` if Redis is down (still 200, everything works); `503
  "unhealthy"` if the database is down.

## Things that are true everywhere

- Timestamps are UTC, ISO-8601. Responses have no timezone suffix (naive
  UTC), so treat them as UTC when parsing. Requests may send `...Z` or no
  suffix.
- IDs are UUID strings, not integers.
- Soft delete is the convention (`is_active=false`), not hard deletes.
  Exceptions: `DELETE /sessions/{id}` (only while `status="scheduled"`, hard
  delete); `DELETE /enrollments/{id}` and `DELETE /devices/{id}` are soft.
- **Deleting an account** (`DELETE /users/me`, password required) deactivates
  it immediately and anonymises its personal data after 30 days.
- Free-text input is HTML-escaped when stored (`<` → `&lt;`, etc.), so render
  it as text, not HTML.
- **Client IP** = the first `X-Forwarded-For` address if present, otherwise
  the connection address. Never set that header from browser code.
- **CORS** allows `http://localhost:3000` and `http://localhost:8501` (plus
  whatever `CORS_ORIGINS` adds in `docker-compose.yml`). Exposed headers:
  `Retry-After`, `X-Request-ID`.
