# Notes for Module 1 (Frontend) — liveness challenge

From Module 3, after testing the challenge flow on real recordings captured
exactly like the app (5 fps, 8 frames per step, 640 px, JPEG quality 70).
Background and measurements: `module3-face-recognition/CHANGES.md`.

## What works now

Since the Module 3 liveness PR (#7) was merged into `main`,
`POST /checkins/challenge/{id}/verify` really answers `passed` / `failed` (it
used to be always `unverified`; rebuild `face-recognition` to get it), and
`failed_step` comes from our per-step detection. Your `MISSED_HINTS` texts fit
it as they are.

**Keep as is:**
- **Raw, unflipped frames.** `drawImage` with the CSS-mirrored preview
  (`-scale-x-100`) is exactly right. If frames were ever flipped, left and
  right would swap and every turn step would fail.
- **The blink prompt "Blink a few times".** Blinks are detected reliably.

## Change: head-turn prompt wording

File: `lib/liveness/challenge.ts`, `PROMPTS`.

| Step | Now | Suggested |
|---|---|---|
| `blink` | "Blink a few times" | Keep |
| `turn_left` | "Slowly turn your head to your left" | "Turn your head to your left, **then look back at the camera**" |
| `turn_right` | "Slowly turn your head to your right" | "Turn your head to your right, **then look back at the camera**" |

**Why:** a turn only counts if the head comes back toward centre (the
backend's contract, API-FOR-FACE-RECOGNITION.md §3). Each step is recorded for
only ~1.4 s (8 frames, starting 0.5 s after the prompt), and nothing is
recorded after the last step. With "**Slowly**", a student is often still
turning when recording stops - so when the turn is the **last** step, the
look-back is never captured and they get "We couldn't see you turn your
head…". A turn as the first step is usually fine (the return shows up in the
next step's frames).

From real recordings of a single `turn_left`:

| How the turn was done | Result |
|---|---|
| Slow, app timing (yaw 0.04 → 0.52, still turning at the last frame) | Failed - no look-back recorded |
| Fast, app timing (turned and back within the step) | Passed |
| Slow, plus 5 extra frames with a "Look back" prompt | Passed |

## Optional: record a little longer after the last step

More robust than wording alone: after the last step, record ~5 more frames
(1 s, same 200 ms interval) with the prompt "Look back at the camera". That's
2 steps × 8 + 5 = **21 frames**, within the backend's 30-frame cap (3 steps:
29). Tested: passes.

## Pending

We've also asked the backend whether the "then back toward centre"
requirement can be dropped. If they agree, the wording change becomes
optional - but it doesn't hurt either way.
