/** Pure liveness-challenge helpers: step prompts, the frame capture plan, and the client-side freshness window. */

export const HARD_MAX_FRAMES = 30

export const CAPTURE = {
  intervalMs: 200,
  framesPerStep: 8,
  countdownMs: 3000,
  leadInMs: 500,
  gapMs: 500,
  hardMaxFrames: HARD_MAX_FRAMES,
  freshForMs: 80_000,
} as const

const PROMPTS: Record<string, string> = {
  blink: 'Blink a few times',
  turn_left: 'Slowly turn your head to your left',
  turn_right: 'Slowly turn your head to your right',
}

/** Returns the on-screen instruction for a challenge action, with a generic prompt for unknown actions. */
export function promptFor(action: string): string {
  return PROMPTS[action] ?? `Please do this now: ${action.replace(/_/g, ' ')}`
}

export interface StepPlan {
  action: string
  prompt: string
  startMs: number
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
  let cursor: number = CAPTURE.countdownMs
  sequence.forEach((action, index) => {
    const first = cursor + CAPTURE.leadInMs
    const frameOffsetsMs = Array.from({ length: perStep }, (_, i) => first + i * CAPTURE.intervalMs)
    const endMs = frameOffsetsMs[frameOffsetsMs.length - 1] + (index < sequence.length - 1 ? CAPTURE.gapMs : 0)
    steps.push({ action, prompt: promptFor(action), startMs: cursor, frameOffsetsMs, endMs })
    cursor = endMs
  })
  return { steps, totalFrames: perStep * sequence.length, durationMs: cursor }
}

/** True while a challenge fetched at fetchedAtMs (monotonic clock) is still safe to submit. */
export function isChallengeFresh(fetchedAtMs: number, nowMs: number): boolean {
  return nowMs - fetchedAtMs < CAPTURE.freshForMs
}
