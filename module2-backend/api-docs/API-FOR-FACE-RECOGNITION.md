# Module 2 Backend API — For Module 3 (Face Recognition)

Read [API-CONVENTIONS.md](API-CONVENTIONS.md) first for general context,
but note: **this file is the opposite direction from the other two.**
Module 1 and Module 4 call *us* (Module 2). For Module 3, it's reversed —
**Module 2 calls you.** There's nothing here for you to call on us; this
document is the contract your service needs to implement so our calls to
you succeed.

---

## Current status (as of 2026-08-26)

`module3-face-recognition` is still a 501 stub for all endpoints, per our
last check. Nothing about that blocks you from building against this
contract right now — it's exactly what our client code
(`app/services/face_client.py`) already assumes and has been tested
against (currently every call gets `None` back and we degrade gracefully,
which is the expected behavior when you're down or unbuilt).

## How we call you

- **Base URL**: `settings.FACE_SERVICE_URL`, defaults to
  `http://localhost:8001` in dev, `http://face-recognition:8000`-style
  hostname in docker-compose. Confirm the actual configured value with
  whoever owns `docker-compose.yml`.
- **No authentication** — these are calls, we treat this as an internal
  service-to-service call, not something a caller token flows through.
- **5-second timeout**, strictly enforced (`httpx` client timeout). If you
  don't respond within 5s, we treat it as a failure and move on — see
  "What happens if you fail" below.
- **Every call is a `POST` with a JSON body**, and we expect a JSON
  response back. Non-2xx status, a timeout, a connection failure, or
  unparseable JSON are all treated identically (see below) — there's no
  special handling for e.g. `503` vs `500` on our side, so pick whatever
  status codes make sense to you for your own logging/observability
  without worrying about how we'll react differently.

## What happens if you fail (or haven't started)

We wrap every call in a lightweight in-process circuit breaker: any
failure opens a 30-second cooldown **per endpoint path**, during which
further calls to that same path skip the network entirely and we
immediately treat it as failed, without even trying to reach you. This
means:

- You won't get hammered with retries while you're down or during your own
  development/restarts.
- If you're slow rather than down, we still cut you off at 5s per call —
  don't design around us waiting longer.
- Every one of our endpoints that calls you has a defined fallback
  behavior for when you're unreachable (documented per-endpoint below) —
  none of our endpoints hard-fail just because you're not answering.

This is real production behavior on our side, not just a test
accommodation — build and test your service standalone without needing to
worry about triggering some special "test mode" on our end.

---

## The four endpoints you need to implement

### 1. `POST /face/enroll`

**We send:**
```json
{ "user_id": "uuid string", "image": "base64 PNG/JPEG, no data: URL prefix", "camera_consent": true }
```

**We read from your response:**
```json
{ "enrollment_successful": true, "face_template_hash": "...", "quality_score": 0.0 }
```
- `enrollment_successful: false` (or a failed/timed-out call) → we tell our
  caller **400 NO_FACE_DETECTED** (no face found) — decide based on
  whichever failure reason actually applies on your end, we just need the
  boolean.
- `face_template_hash`: stored as-is on `users.face_embedding_hash`
  (`VARCHAR(64)`, nullable) — see the "hash format" section below for what
  this needs to be.
- `quality_score`: passed straight through to the caller, not otherwise
  validated on our end.
- Any failure (timeout, 5xx, connection refused, bad JSON) → we return
  **503 FACE_SERVICE_UNAVAILABLE** to the caller. There's no "enroll
  anyway" fallback for this one — a failed enrollment call is a real
  failure to us, unlike the others below.

### 2. `POST /face/verify`

**We send:**
```json
{ "image": "base64 PNG/JPEG", "reference_template_hash": "the user's stored users.face_embedding_hash" }
```

**We read from your response:**
```json
{ "match_passed": true, "match_score": 0.0, "current_template_hash": "..." }
```
- Called during check-in, only when the student submitted a liveness
  image **and** already has a `face_embedding_hash` on file.
- On failure/timeout: we degrade to `face_match_passed = None`,
  `face_match_score = None` — this does **not** fail the check-in, it just
  means that signal contributes nothing to the risk score.
- `current_template_hash` is stored on the check-in row
  (`checkins.face_embedding_hash`) as a record of that specific attempt's
  computed hash — separate from the user's enrolled reference hash.

### 3. `POST /liveness/check`

**We send:**
```json
{ "challenge_response": "base64 image", "challenge_type": "passive" }
```

**We read from your response:**
```json
{ "liveness_passed": true, "liveness_score": 0.0 }
```
- On failure/timeout: we degrade to `liveness_passed = None`,
  `liveness_score = 0.0` — deliberately **`None`, not `False`** on our
  side, because an explicit `liveness_passed: false` triggers a hard
  reject in our risk-scoring override regardless of the numeric score,
  and an unreachable/unattempted check should never do that. **Only send
  `liveness_passed: false` when you've actually determined liveness
  failed** — don't default to `false` on your own uncertain/edge cases,
  since that has a much stronger effect on our end than a low score would.

### 4. `POST /risk/assess`

**We send** (only when a liveness image was actually submitted — otherwise
we skip this call entirely and use our own local fallback formula):
```json
{
  "liveness_score": 0.0,
  "face_match_score": 0.0,
  "user_agent": "...",
  "ip_address": "...",
  "geolocation": { "latitude": 0.0, "longitude": 0.0, "accuracy": 0.0 }
}
```

**We read from your response:**
```json
{ "risk_score": 0.0 }
```
We only look for the `risk_score` key — if present, we use it as-is
(0.0–1.0). If absent, or the call fails/times out, we compute an
equivalent score ourselves from `liveness_score`/geofence
distance/device-trust locally instead of blocking the check-in.

---

## Face embedding hash format — read before you build enrollment

**Team decision: SimHash, not SHA-256**, despite what the original written
spec examples show. Reasoning: `/face/verify` needs *fuzzy* matching (the
same face photographed twice produces a similar-but-not-identical
embedding), and SHA-256 has zero tolerance for that — a single bit of
difference produces a completely different hash, making exact-match
comparison useless for this purpose. A **locality-sensitive hash**
(SimHash: 256 hyperplanes → 64 hex characters) is what actually supports
"close enough" comparison.

On our side this is just an opaque `VARCHAR(64)` string either way — we
never compute, interpret, or compare it ourselves, we just store what you
give us and pass it back to you on the next `/face/verify` call. **You own
the actual hashing/comparison logic entirely.** Just make sure whatever
you produce fits in 64 characters and is a stable, comparable
representation across two photos of the same real face.

## Nothing here needs authentication or waits on you

Every one of our endpoints that calls you (`face enrollment`, check-in
liveness/face-match/risk-assess) already works correctly with you fully
down — that's been tested and verified on our end (see
`module2-backend/KNOWN-ISSUES.md`'s Module 3 entry for exactly what's
verified vs. not). You can build and deploy incrementally — implementing
just `/face/enroll` first and leaving the other three 501 is fine, our
circuit breaker treats each path independently.
