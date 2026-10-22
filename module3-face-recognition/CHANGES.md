# Module 3 (Face Recognition) — Changes

What changed in this service, why, and what to keep in mind when changing it
again. Newest first. The backend's side of the contract is in
`module2-backend/api-docs/API-FOR-FACE-RECOGNITION.md` and
`CHANGES-2026-10-01.md`.

---

## 2026-10-22 — Concurrency and `/face/verify` null result

### Summary

| Change | Where | Why |
|---|---|---|
| `/face/verify` returns `match_passed: null` when it couldn't compare | `verify_face`, `FaceVerifyResponse` | The backend rejected blurry/no-face check-ins as "wrong person" |
| Image endpoints are sync (`def`); `/risk/assess` stays `async` | route handlers | One image request used to block every other request |
| One set of face models per process, used under one lock | `_model_lock`, `_face_detector`, `_face_mesh_static` | Models were rebuilt on every call; per-thread copies hung under load |
| dlib uses MediaPipe's face box instead of detecting again | `extract_face_embedding`, `_dlib_face_box` | dlib's own detector was most of each request's time |
| 2 uvicorn worker processes | `Dockerfile` (`WEB_CONCURRENCY=2`) | Only way to run more than one dlib call at a time |

### 1. `/face/verify`: `null` instead of `false` when no comparison happened

`match_passed` is now `Optional[bool]`. It is `null` when the image can't be
decoded, no face is found, no embedding can be produced, or the reference hash
is invalid (`face_detected: false` in the first three cases). `false` now only
means "compared two faces and they differ".

**Why:** the backend reads only `match_passed`, and on a session that requires
face match, `false` is a hard reject (`face_match_failed`). A blurry photo was
being treated as a different person. `null` makes it "unverified" (flagged
for review) instead. This is what API-FOR-FACE-RECOGNITION.md §2 asks for. The
public no-face test accepts it (`face_detected: false`).

### 2. How requests run now

- **Image endpoints** (`/face/enroll`, `/face/verify`, `/face/match`,
  `/liveness/check`) are plain `def`, so FastAPI runs them on its thread pool
  (about 40 threads per process). Before, they were `async def` but did
  blocking CPU work, so each one froze the whole server until it finished.
- **`/risk/assess`** stays `async def`. It's pure arithmetic and never blocks.
  As a sync handler it had to wait for a free thread, and under load every
  thread was busy with image requests, so it took seconds.
- **Face models**: each process builds one MediaPipe face detector, one
  MediaPipe face mesh and (via `face_recognition`) one set of dlib models,
  once at startup. All model calls go through `_model_lock`, so **one request
  at a time per process uses the models**.
  - dlib is about 95% of the work and isn't safe to call from several threads
    anyway, so the lock costs almost no throughput.
  - **Don't switch to per-thread model copies.** That was tried: right after a
    restart, 100 parallel requests made dozens of threads build models at the
    same time and requests hung for 120 s; even when warm, ~40 threads fought
    over the CPU and responses came back in clumps.
- **dlib face box**: dlib used to run its own face detector after MediaPipe had
  already found the face. It now gets MediaPipe's box
  (`known_face_locations`), falling back to its own detector only if the box
  is unusable. Each embedding went from 0.8–2.3 s to a steady ~0.35 s.
  Matching was checked on the sample images before switching:

  | Pair | Distance, dlib's box | Distance, MediaPipe's box |
  |---|---|---|
  | obama vs obama2 | 0.346 | 0.342 |
  | obama vs obama3 | 0.332 | 0.329 |
  | obama2 vs obama3 | 0.428 | 0.432 |
  | obama vs biden | 0.840 | 0.842 |
  | obama2 vs biden | 0.816 | 0.809 |
  | obama3 vs biden | 0.870 | 0.870 |

  The match threshold is 0.6. The same image's embedding moves only 0.04–0.07
  between the two boxes, so faces enrolled before this change still match.

### 3. Worker processes (`WEB_CONCURRENCY`)

The `Dockerfile` sets `ENV WEB_CONCURRENCY=2`. uvicorn uses it as the default
for `--workers`, so the container runs **2 processes**. The `CMD` is unchanged.

- Each worker has its own models and its own lock, so **workers = how many
  dlib calls can run at the same time**.
- Each worker uses about **280 MB of RAM** (measured on Windows, idle after a
  load test). 2 workers ≈ 560 MB.
- More workers only help if the machine has a free CPU core for each one.
- To change it without rebuilding, set it in `docker-compose.yml`:

  ```yaml
  face-recognition:
    environment:
      WEB_CONCURRENCY: 4
  ```

  Rule of thumb: no more than the number of CPU cores you can spare for this
  service, and keep about 300 MB of RAM per worker.

### 4. Measured performance and known limits

Measured locally (12-core Windows laptop, Python 3.12, `sample_images/obama.jpg`
at 910×1137) with an even mix of `/liveness/check`, `/face/verify` and
`/risk/assess` sent all at once:

| Setup | Parallel requests | Total time | Image requests over 5 s | `/risk/assess` median |
|---|---|---|---|---|
| Before (1 process, async + blocking) | 60 | 38 s | 35 / 40 | 18.3 s |
| Now, 2 workers | 30 | 5.2 s | 6 / 20 | 0.7 s |
| Now, 2 workers | 60 | 12.3 s | 25 / 40 | 1.4 s |
| Now, 2 workers, warm | 100 | 21.9 s | 54 / 67 | 1.3 s |
| Now, 2 workers, just restarted | 100 | 14.4 s | 55 / 67 | 0.8 s |

No errors in any run after the change. Public tests: 15/15.

**The limit:** each image request costs about 0.35 s of dlib time plus
decoding and MediaPipe, and each worker does one at a time. Measured, 2
workers get through about **3–4 image requests per second** (20 in 5.2 s, 40
in 12.3 s, 67 in 21.9 s). A check-in with a photo calls `/liveness/check` and,
if the student has enrolled a face, `/face/verify`: about 2 image requests. So
roughly **8–10 check-ins arriving together finish inside the backend's 5 s
timeout**. Beyond that, some calls go over 5 s.

**What happens past the limit:** nothing breaks. The backend stops waiting at
5 s (15 s for frame bursts), scores the check-in itself, and pauses calls to
that endpoint for 30 s (its circuit breaker). Those check-ins are flagged for
review instead of auto-approved. The hidden stress test (~100 concurrent
check-ins) will hit this.

**Ways to raise the limit later:** more workers (cores and RAM permitting),
more containers behind a load balancer, or skipping the dlib embedding in
`/liveness/check` (the backend doesn't read its `face_embedding_hash`, but the
public tests use it as a fallback, so check before removing it).

**Frame bursts (not built yet):** the burst path will mostly run MediaPipe
(5–8 ms per frame) plus one dlib embedding, so a ~16-frame burst should cost
about 0.5 s of model time. Re-measure once it exists.
