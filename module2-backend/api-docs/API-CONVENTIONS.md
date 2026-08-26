# Module 2 Backend — Shared API Conventions

Read this first, then whichever of these applies to you:

- [API-FOR-FRONTEND.md](API-FOR-FRONTEND.md) — Module 1
- [API-FOR-FACE-RECOGNITION.md](API-FOR-FACE-RECOGNITION.md) — Module 3
- [API-FOR-DASHBOARD.md](API-FOR-DASHBOARD.md) — Module 4

This describes the **actual implemented behavior** of the Module 2 backend as of
**2026-08-26** (all phases complete, 77/77 scored public test points, 81/81
non-skipped tests passing). Where the written project spec and the actual
implementation disagree, what's below is what's actually running — see
`module2-backend/KNOWN-ISSUES.md` if you want the full reasoning for any
specific deviation.

---

## Base URL

- Local dev (docker-compose): `http://localhost:8000`
- All endpoints below are under `/api/v1` **except**: `GET /health`, `GET /`,
  and `GET /metrics` (root-level, no prefix — see API-FOR-DASHBOARD.md).

## Authentication

JWT bearer tokens, `HS256`. Get one via `POST /api/v1/auth/register` then
`POST /api/v1/auth/login`, or just `/login` if the account already exists.

```
Authorization: Bearer <access_token>
```

- **Access token**: 60 minutes. **Refresh token**: 7 days. Refresh via
  `POST /api/v1/auth/refresh` with `{"refresh_token": "..."}` before the
  access token expires — there's no automatic renewal.
- Token claims: `sub` (user id), `email`, `role`, `type` (`access` or
  `refresh`), `iat`, `exp`. Don't rely on any claim beyond what the `/me`
  endpoints already return — nothing sensitive is added.
- **401** = missing/invalid/expired token. **403** = valid token, wrong role
  or wrong ownership of the specific resource. Don't conflate the two when
  handling errors.

## Roles

`student | instructor | ta | admin` — one global role per user
(`users.role`), not per-course. Course/session-level permissions (e.g. "is
this instructor allowed to touch *this* course") are a separate, additional
check documented per-endpoint in the module-specific files.

Registration accepts **any** role including `admin` — there's no
invite-only/approval gate on signup. This is a deliberate project decision,
not an oversight.

## Error format

Every error response **except 422** looks like:

```json
{ "detail": "Human-readable message", "code": "MACHINE_READABLE_CODE" }
```

**422** (Pydantic validation failures — e.g. missing required field, password
under 8 characters, malformed email) stays FastAPI's default shape instead:

```json
{ "detail": [ { "type": "...", "loc": [...], "msg": "...", ... } ] }
```

Common `code` values you'll actually see: `EMAIL_ALREADY_REGISTERED`,
`INVALID_CREDENTIALS`, `ACCOUNT_DISABLED`, `INVALID_TOKEN`,
`INSUFFICIENT_PERMISSIONS`, `*_NOT_FOUND` (course/session/user/device/
enrollment/checkin/student), `ALREADY_ENROLLED`, `ALREADY_CHECKED_IN`,
`SESSION_NOT_ACTIVE`, `SESSION_WINDOW_CLOSED`, `DEVICE_FINGERPRINT_TAKEN`,
`CAMERA_CONSENT_REQUIRED`, `RATE_LIMITED`, `FACE_SERVICE_UNAVAILABLE`,
`INTERNAL_ERROR`. Build error handling against `code`, not the `detail`
string — the string is for display, the code is for logic.

## Pagination

List endpoints that paginate return:

```json
{ "items": [...], "total": 123, "limit": 50, "offset": 0 }
```

`limit`/`offset` are query params (defaults and max vary per endpoint — see
each file). **Not every list endpoint is paginated** — some documented
"plain array" endpoints (e.g. `/sessions/active`, `/checkins/my-checkins`)
really do just return `[...]` directly. Check each endpoint's entry rather
than assuming.

## Rate limiting

All 429s include a `Retry-After` header (seconds) and
`{"code": "RATE_LIMITED"}`.

| Limit | Value | Keyed by | Notes |
|---|---|---|---|
| Registration | 300/hour | IP | Deviates from the written spec's literal `10` — see `KNOWN-ISSUES.md` §1/§4 if curious why. Handle a 429 here the same as any other error, don't assume it can't happen. |
| Login | 60/hour | IP | Counts **failed** attempts only — repeated successful logins from one IP/network never trigger this. |
| Check-in submission | 10/minute | authenticated user | Applies to `POST /checkins/` specifically. |
| Everything else (API-wide) | 1000/hour | authenticated user | Applies once you're past `get_current_user` — i.e. almost every authenticated call. |

## Things that are true everywhere

- All timestamps are UTC, ISO-8601, no timezone suffix in responses (naive
  UTC — treat as UTC when parsing).
- IDs are UUID strings (`String(36)`), not integers.
- Soft-delete is the convention throughout (`is_active=false`), not hard
  deletes — except `DELETE /sessions/{id}` (only allowed while
  `status="scheduled"`, hard row delete) and `DELETE /enrollments/{id}`
  /`DELETE /devices/{id}` (soft, flips `is_active`/sets `revoked_at`).
- CORS is open to `http://localhost:3000` and `http://localhost:8501` in
  dev — tell whoever owns deployment config if your dev server runs on a
  different port.
