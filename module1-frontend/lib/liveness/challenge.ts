/** Pure liveness-challenge helpers: step prompts, the frame capture plan, and the client-side freshness window. */

export const HARD_MAX_FRAMES = 30

export const CAPTURE = {
  intervalMs: 200,
  framesPerStep: 10,
  countdownMs: 3000,
  captureMs: 2000,
  hardMaxFrames: HARD_MAX_FRAMES,
  freshForMs: 80_000,
} as const

const PROMPTS: Record<string, string> = {
  blink: 'Close your eyes for 1 second and open them',
  turn_left: 'Turn your head to your left and look back in the camera within 2 seconds',
  turn_right: 'Turn your head to your right and look back in the camera within 2 seconds',
}

const MISSED_HINTS: Record<string, string> = {
  blink: "We couldn't see you blink.",
  turn_left: "We couldn't see you turn your head to your left.",
  turn_right: "We couldn't see you turn your head to your right.",
}

/** Returns a hint naming the step that wasn't detected, or null when the step is missing or unknown. */
export function missedStepHint(step: string | null | undefined): string | null {
  return step ? MISSED_HINTS[step] ?? null : null
}

/** Returns the on-screen instruction for a challenge action, with a generic prompt for unknown actions. */
export function promptFor(action: string): string {
  return PROMPTS[action] ?? `Please do this now: ${action.replace(/_/g, ' ')}`
}

export interface StepPlan {
  action: string
  prompt: string
  startMs: number
  captureStartMs: number
  frameOffsetsMs: number[]
  endMs: number
}

export interface CapturePlan {
  steps: StepPlan[]
  totalFrames: number
  durationMs: number
}

/** Plans when each frame is taken; returns null when the challenge cannot fit at least one frame per step. */
export function planCapture(sequence: string[], maxFrames: number): CapturePlan | null {
  if (sequence.length === 0) return null
  const cap = Math.min(Number.isFinite(maxFrames) ? maxFrames : 0, CAPTURE.hardMaxFrames)
  const perStep = Math.min(CAPTURE.framesPerStep, Math.floor(cap / sequence.length))
  if (perStep < 1) return null
  const steps: StepPlan[] = []
  let cursor = 0
  sequence.forEach((action) => {
    const captureStartMs = cursor + CAPTURE.countdownMs
    const frameOffsetsMs = Array.from({ length: perStep }, (_, i) => captureStartMs + i * CAPTURE.intervalMs)
    const endMs = captureStartMs + CAPTURE.captureMs
    steps.push({ action, prompt: promptFor(action), startMs: cursor, captureStartMs, frameOffsetsMs, endMs })
    cursor = endMs
  })
  return { steps, totalFrames: perStep * sequence.length, durationMs: cursor }
}

/** True while a challenge fetched at fetchedAtMs (monotonic clock) is still safe to submit. */
export function isChallengeFresh(fetchedAtMs: number, nowMs: number): boolean {
  return nowMs - fetchedAtMs < CAPTURE.freshForMs
}
