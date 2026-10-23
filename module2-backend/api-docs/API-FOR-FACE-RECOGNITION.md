# Module 2 Backend API — For Module 3 (Face Recognition)

Read [API-CONVENTIONS.md](API-CONVENTIONS.md) for general context, but note:
**this file is the opposite direction from the other two.** Modules 1 and 4
call *us*; for Module 3, **Module 2 calls you.** This is the contract your
service implements so our calls succeed. **Your tasks:** the Module 3 table
in [CHANGES-2026-10-01.md](CHANGES-2026-10-01.md). **Why things changed:**
[CHANGELOG.md](CHANGELOG.md). Last updated 2026-10-23.

---

## How we call you

- **Base URL**: `FACE_SERVICE_URL`, i.e. `http://face-recognition:8001`
  inside docker-compose (`http://localhost:8001` from your machine).
- **No authentication**: internal service-to-service calls.
- **Every call is a `POST` with a JSON body**, and we expect JSON back.
- **5-second timeout** for each step of a call: connecting, sending the
  request, waiting for your response to start, and the gap between response
  chunks. It's not a hard cap on the whole call: a reply that trickles in
  slowly can take longer in total. Your replies are small JSON objects, so in
  practice a call that isn't answered within ~5 s fails. Exception:
  `/liveness/check` calls that carry a frame burst get **15 seconds** per
  step (`LIVENESS_TIMEOUT_SECONDS`); single-image calls keep 5 s.
- **Concurrency:** the backend handles 100+ simultaneous check-ins, and each
  check-in with a photo or a frame burst can call `/liveness/check`,
  `/face/verify` and `/risk/assess`. On top of that, each liveness **retry**
  (`POST /checkins/challenge/{id}/verify`, up to 3 per student per session)
  is one `/liveness/check` frame-burst call. The hidden stress tests use ~100
  concurrent users, so load-test with 50–100 parallel requests. If you're
  slow, only the check-ins wait; the rest of the backend stays responsive.
- **Images:** we forward the base64 exactly as the client sent it (normally
  no `data:` prefix and no whitespace). Anything over 10,000,000 base64
  characters is refused before it reaches you.

## What happens when a call fails

| Your response | What we do |
|---|---|
| 2xx with JSON | Use it |
| **4xx** | Treat **that one call** as failed and fall back for that request. Other requests keep calling you normally |
| **5xx**, timeout, connection error, invalid JSON | Treat as failed **and stop calling that endpoint for 30 s** (circuit breaker per path), then try again |

During the 30 s cooldown we score locally, so none of our endpoints
hard-fail because you're down. A service that doesn't start answering
within 5 s is treated as failed.

---

## The four endpoints

### 1. `POST /face/enroll`

**We send:**
```json
{ "user_id": "uuid string", "image": "base64 PNG/JPEG", "camera_consent": true }
```
(We check camera consent ourselves first, so `camera_consent` is always
`true` in practice.)

**We read:**
```json
{ "enrollment_successful": true, "face_template_hash": "...", "quality_score": 0.0 }
```
- `enrollment_successful: true` → we store `face_template_hash` on the user
  (`VARCHAR(64)`) and return `200` to the student.
- `enrollment_successful: false` in a 2xx → we return **`400
  NO_FACE_DETECTED`**. **Your current 201 + `false` behaviour is what we
  rely on. Keep it.** The course's public tests accept it.
- A 4xx/5xx/timeout → we return **`503 FACE_SERVICE_UNAVAILABLE`** to the
  student. If you ever switch "no face" to a 400, tell us first: students
  would see "service unavailable" instead of "no face detected".

### 2. `POST /face/verify`

**We send:**
```json
{ "image": "base64 PNG/JPEG", "reference_template_hash": "the user's stored hash" }
```
**We read:**
```json
{ "match_passed": true, "match_score": 0.0, "current_template_hash": "..." }
```
- Called during check-in when the student sent a photo or a frame burst
  **and** has an enrolled face. We send the photo, or else the burst's
  middle frame. With a verified challenge we always send the verified
  burst's middle frame, so the face that did the movements is the one
  compared.
- `current_template_hash` is stored on the check-in row as a record of that
  attempt.
- **What `match_passed` does now:**
  - `false` on a session that **requires face match** → the check-in is
    **rejected** (`face_match_failed`, a hard reject).
  - On other sessions it only affects the score.
  - On failure we use `None` → on a face-required session the check-in is
    **flagged for review**, not rejected.
- **Only return `match_passed: false` when you've actually compared two
  faces and they differ.** We read only `match_passed`, `match_score` and
  `current_template_hash`; any other field (e.g. `face_detected`) is
  ignored, so a `false` is a hard reject whatever else you send. For "no
  face found" or "can't decide", return **`match_passed: null`** (→ flagged
  for review), or a **4xx** (that call alone falls back, and the circuit
  breaker stays closed).

### 3. `POST /liveness/check`

Two request shapes. **Keep supporting the first**: the course's public
tests call you directly with a single image and `"challenge_type":
"passive"`, and most check-ins still send one photo.

**(a) Single image:**
```json
{ "challenge_response": "base64 image", "challenge_type": "passive" }
```

**(b) Frame burst.** Sent when the student's app captured a short burst
while performing a challenge:
```jsonc
{
  "challenge_response": "base64 image",          // still sent: the middle frame, so an older build keeps working
  "challenge_type": "sequence",                  // "sequence" when the backend issued a challenge;
                                                 // otherwise whatever the client sent ("blink", "passive", ...)
  "frames": ["base64 frame 1", "base64 frame 2", "..."],   // ordered, oldest first, 1–30 frames
  "challenge_sequence": ["blink", "turn_left"]   // present only when the backend issued a challenge
}
```
- `frames`: ~5 frames per second, about 8 per step (≈16 frames for a 2-step
  challenge). Each frame is under the per-image limit; the whole request
  is under 15 MB, so expect small JPEGs (≈640 px wide).
- `challenge_sequence`: 1–3 actions, never the same action twice in a row.
  **Actions (v1):**

  | Action | What to detect across the frames |
  |---|---|
  | `blink` | Eyes open → closed → open (eye aspect ratio from the face mesh) |
  | `turn_left` | Head yaw to the **student's** left past a threshold, then back toward centre. Frames are **not mirrored** (see below), so the face turns toward the **image's right** |
  | `turn_right` | Same, to the student's right (toward the image's left) |

  **Frames are never mirrored.** The app captures the raw camera image
  (`getUserMedia` → canvas, no flip), so you see what someone facing the
  student would see: the student's left is the image's right. If the app
  ever mirrors its on-screen preview, that's CSS only and doesn't change
  the frames. Yaw sign conventions differ between libraries, so check yours
  with a quick test (turn to your own left on camera and log the yaw) rather
  than assuming the sign.

  More actions (`nod`, `open_mouth`) may be added later in the same format.
  Treat an unknown action as "not performed".
- Steps must happen **in the order given**.

**We read:**
```jsonc
{
  "liveness_passed": true,      // as before: your anti-spoof verdict
  "liveness_score": 0.0,        // as before
  "challenge_passed": true,     // were all steps performed, in order? Only needed for shape (b) with challenge_sequence
  "steps_passed": [true, false] // one per step, in sequence order. Please send it: we log it, and
                                // we tell the student which step to redo (the first false one)
}
```

**How we decide (frame burst with a challenge):**

| Your answer | Outcome |
|---|---|
| `challenge_passed: false` | Steps not performed. The student may **retry** (3 attempts per session, a new sequence each time); without a later pass the check-in is **flagged for review**, not rejected |
| `challenge_passed: true` + `liveness_passed: true` | Passed |
| `challenge_passed: true` + `liveness_passed: null` | Unverified (no attempt used) |
| `challenge_passed` missing or `null` (e.g. older build, or you couldn't tell) | **Unverified** → at most **flagged for review**, unless `liveness_passed` is `false` |
| `liveness_passed: false` (any `challenge_passed`) | Spoof → **no more attempts**, check-in **rejected** (the student can appeal) |
| Call failed / timed out | Unverified; the student's attempt isn't used up |

**When you're called:** usually by `POST /checkins/challenge/{id}/verify`,
right after the student performs the challenge and **before** the
check-in, so they can retry. The check-in then reuses that answer without
calling you again. If the app skips the verify step, you're called at the
check-in as before. Same request and response either way.

Your current build ignores the unknown fields and scores
`challenge_response` as one image. That's safe: without `challenge_passed`
we never auto-approve a challenged check-in. But until you return it,
every verify answers "unverified", so students can't retry yet.
- `liveness_passed: false` → **always rejects** the check-in
  (`liveness_failed`, hard reject), whatever the score.
- `liveness_passed: null` (e.g. no face found), or a failed call → the
  check-in is never auto-rejected for it: on a session that requires
  liveness it's **flagged for review** (`liveness_unverified`). Your current
  `null` for "no face detected" is exactly right.
- **Only send `false` when you've determined the image is a spoof**
  (printed photo, screen replay, flat face mesh). Don't default to `false`
  for uncertain cases.

### 4. `POST /risk/assess`

Only called when the student sent a photo or a frame burst; otherwise we
skip it and use a local formula.

**We send:**
```json
{
  "liveness_score": 0.0,
  "face_match_score": 0.0,
  "user_agent": "...",
  "ip_address": "...",
  "geolocation": { "latitude": 0.0, "longitude": 0.0, "accuracy": 0.0 }
}
```
- `face_match_score` is `null` if there was no face comparison.
- `ip_address` = the first `X-Forwarded-For` address if present, otherwise
  the connection address (normalised; may be IPv6). Inside docker-compose
  it's usually a **private Docker IP** (`172.x`).
- `geolocation` is **only included when the client sent
  `location_accuracy_meters`**, because your schema requires `accuracy` (a
  missing accuracy used to cause a 422).
- Check-ins that fail our earlier checks never reach you: outside
  Singapore, already checked in, not enrolled, too large, and so on.

**We read:**
```json
{ "risk_score": 0.0 }
```
We only use `risk_score` (0.0–1.0) as the base score, then add our own
signals (device, GPS accuracy, impossible travel, replay, …) and decide the
outcome ourselves. Your `risk_level`, `pass_threshold` and
`recommendations` are fine to return but aren't used for decisions.

**Private IPs:** the course rule (enforced by the backend) treats private
and local IPs as **on-campus**. Your `detect_vpn_proxy()` currently scores
them as a likely VPN (0.7 confidence), which raises the risk of every
genuine check-in made inside Docker. We suggest treating private and
loopback addresses as neutral.

---

## Face embedding hash format

**Team decision: SimHash, not SHA-256**, despite the original spec examples.
`/face/verify` needs *fuzzy* matching: two photos of the same face produce
similar but not identical embeddings. SHA-256 changes completely for a
1-bit difference, so it can't match them. A locality-sensitive hash
(SimHash, 64 hex characters) can.

On our side it's an opaque `VARCHAR(64)`: we store what you return and pass
it back on `/face/verify`. **You own the hashing and comparison.** Keep it at
most 64 characters and stable across photos of the same face. **Never return
raw images or embeddings:** only the hash is stored, and the hidden privacy
audit inspects the database for raw biometric data.

## Your `/metrics` endpoint

`module4-observability/prometheus.yml` scrapes
`face-recognition:8001/metrics`. It returns 404 today, so the Prometheus
target shows "down". Adding `prometheus_client` with a `GET /metrics` route
fixes it.
