# Module 3 (Face Recognition) — Changes

What changed in this service, why, and what to keep in mind when changing it
again. Newest first. The backend's side of the contract is in
`module2-backend/api-docs/API-FOR-FACE-RECOGNITION.md` and
`CHANGES-2026-10-01.md`.

---

## 2026-10-22 (3) — Private IPs are no longer scored as VPN

`detect_vpn_proxy` now ignores the IP address and only checks the user agent
for VPN keywords. Before, private and loopback addresses (`10.x`,
`172.16–31.x`, `192.168.x`, `127.x`, `::1`) got a 0.7 VPN confidence.

**Why:**
- The course's later clarification email says private/local addresses "may
  be treated as on-campus and allowed". That's newer than the starter
  docstring, which listed them as VPN signs.
- module2-backend asked for it (`CHANGES-2026-10-01.md`, Module 3 §A). Inside
  docker-compose every request reaches us from a private `172.x` address, so
  every genuine check-in was getting VPN risk.
- The backend already rejects public IPs outside Singapore (GeoIP) before
  calling us, so there's no IP check left for us to do.

**Effect** (`/risk/assess` with liveness 0.8, face match 0.85, GPS accuracy 10 m):

| Input | Before | After |
|---|---|---|
| Docker IP `172.18.0.5`, browser user agent | ~0.26 | 0.128 (LOW) |
| Public IP `8.8.8.8`, browser user agent | 0.128 | 0.128 (LOW) |
| Private `10.0.0.1`, `vpn-client` user agent | — | 0.278, network signal still flagged |

The public test that sends `10.0.0.1` with a `vpn-client` user agent still
passes (risk 0.761, `pass_threshold: false`), because the user agent alone
flags it. Public tests 15/15.

**If a hidden test expects a private IP alone to raise risk**, this is the
change to revisit: the old behaviour was to give private/loopback IPs 0.7
confidence in `detect_vpn_proxy`.

### User-agent check: "tor" matched inside ordinary words

The keyword check flagged any user agent containing `vpn`, `proxy`, `tunnel`
or `tor` anywhere. `tor` matched normal browsers, e.g. Android phones with
`motorola` in their user agent, giving genuine students 0.8 VPN confidence.
`tor` now has to be a whole word (`_VPN_USER_AGENT_PATTERN`); the other three
still match anywhere.

| User agent | Before | After |
|---|---|---|
| `... Android 13; motorola edge 40 ...` | VPN | not VPN |
| `Mozilla/5.0 (compatible; Navigator)` | VPN | not VPN |
| `vpn-client`, `MyVPNApp/2.1`, `corp-proxy/1.0`, `SSH Tunnel Client` | VPN | VPN |
| `Tor Browser`, `tor/0.4.8` | VPN | VPN |

---

## 2026-10-22 (2) — Metrics, dependency caps, base64 whitespace

From the Module 3 checklist in `CHANGES-2026-10-01.md` (§1 and §4 M3 C/D).

### `GET /metrics`

Prometheus (`module4-observability/prometheus.yml`, job
`saiv-face-recognition`) scraped `/metrics` and got 404, so the target showed
"down". It now returns:

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `face_request_duration_seconds` | Histogram | `method`, `path`, `status_code` | Latency of every request. `path` is the route (e.g. `/face/verify`), or `unmatched` for unknown URLs. Buckets include 5 s and 15 s, the backend's timeouts |
| `face_enroll_total` | Counter | `outcome`: `success` / `failed` | Enrollments |
| `face_verify_total` | Counter | `outcome`: `match` / `no_match` / `not_compared` | Verifications (`not_compared` = `match_passed: null`) |
| `face_liveness_total` | Counter | `outcome`: `passed` / `failed` / `not_assessed` | Liveness checks (`not_assessed` = `liveness_passed: null`) |

- **Not named `http_request_duration_seconds`** like the backend's: Module 4's
  system-health dashboard sums that name across all jobs without a `job`
  filter, so our latency would be mixed into the backend's API latency and
  error panels. If Module 4 wants a face-service panel, query
  `face_request_duration_seconds`.
- **Counts all workers.** Each worker process has its own counters, and a
  scrape reaches one of them. `PROMETHEUS_MULTIPROC_DIR` (set in the
  Dockerfile) makes prometheus_client write every worker's values to that
  folder, and `/metrics` adds them up. Checked with 2 workers: three scrapes in
  a row gave identical totals that matched the requests sent.
- Run locally without that variable, each worker reports only its own numbers.
  That's fine for development; with one worker it doesn't matter.
- Counting is done by the `_count_outcome` decorator on the three image
  endpoints, so their early returns don't each need a counter line.

### Dockerfile

```dockerfile
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
CMD ["sh", "-c", "rm -rf \"$PROMETHEUS_MULTIPROC_DIR\" && mkdir -p \"$PROMETHEUS_MULTIPROC_DIR\" && exec uvicorn app.main:app --host 0.0.0.0 --port 8001"]
```

- The folder is emptied on every container start, so numbers from before a
  restart don't carry over. Prometheus sees counters reset, which it handles.
- `exec` keeps uvicorn as the container's main process, so `docker stop`
  shuts it down cleanly instead of waiting and killing it.
- uvicorn's arguments are the same as before; `WEB_CONCURRENCY` still sets the
  worker count.

### Dependencies

- `requirements.txt` and the root `requirements-test.txt`: `opencv-python<4.12`
  and `numpy<2`, matching the course's re-released starter (mediapipe 0.10.18
  isn't compatible with newer versions). Installed versions here (4.11, 1.26)
  already satisfy them.
- `prometheus-client==0.19.0` added to `requirements.txt`, the same version as
  module2-backend. **Rebuild the image** (`docker compose up -d --build`) or
  `pip install -r requirements.txt` in your venv.

### Base64 whitespace

`decode_base64_image` now removes spaces and line breaks before decoding. Base64
wrapped across lines is still valid, but strict decoding rejected it, so
`/face/verify` answered "couldn't compare" for a good photo. Checked: a
line-wrapped copy of `obama.jpg` now verifies as a match.

### Performance check

Public tests 15/15. 60 parallel requests with 2 workers and metrics on:
11.6–12.3 s, the same as without metrics (a metric update costs ~6 µs).
**Measurement note:** on Windows, how evenly the 2 workers share connections
varies between server restarts, so the same test can take ~20% longer after
one restart than another. Compare runs from the same server start.

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
for `--workers`, so the container runs **2 processes**. (The `CMD` itself was
changed later for metrics; see the 2026-10-22 (2) entry.)

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
