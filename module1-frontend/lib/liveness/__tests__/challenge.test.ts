import { CAPTURE, isChallengeFresh, planCapture, promptFor } from '@/lib/liveness/challenge'

describe('promptFor', () => {
  it('prompts the three known actions and a generic one for unknown actions', () => {
    expect(promptFor('blink')).toBe('Close your eyes for 1 second and open them')
    expect(promptFor('turn_left')).toBe('Turn your head to your left and look back in the camera within 2 seconds')
    expect(promptFor('turn_right')).toBe('Turn your head to your right and look back in the camera within 2 seconds')
    expect(promptFor('nod_twice')).toBe('Please do this now: nod twice')
  })
})

describe('planCapture', () => {
  it('gives each step a 3 s countdown then a 2 s capture of 10 frames at 5 fps, with no upfront countdown', () => {
    const plan = planCapture(['blink', 'turn_left'], 30)!
    expect(plan.totalFrames).toBe(20)
    expect(plan.steps.map((s) => [s.startMs, s.captureStartMs, s.endMs])).toEqual([
      [0, 3000, 5000],
      [5000, 8000, 10000],
    ])
    expect(plan.steps[0].frameOffsetsMs).toEqual([3000, 3200, 3400, 3600, 3800, 4000, 4200, 4400, 4600, 4800])
    expect(plan.steps[1].frameOffsetsMs[0]).toBe(8000)
    expect(plan.steps[1].frameOffsetsMs[9]).toBe(9800)
    expect(plan.durationMs).toBe(10000)
  })

  it.each([
    [1, 30, 10, 10],
    [2, 30, 10, 20],
    [3, 30, 10, 30],
    [2, 10, 5, 10],
    [3, 4, 1, 3],
  ])('%p steps with max_frames %p -> %p per step, %p total', (steps, maxFrames, perStep, total) => {
    const plan = planCapture(Array.from({ length: steps }, () => 'blink'), maxFrames)!
    expect(plan.steps.every((s) => s.frameOffsetsMs.length === perStep)).toBe(true)
    expect(plan.totalFrames).toBe(total)
  })

  it('never exceeds min(max_frames, 30)', () => {
    for (let maxFrames = 1; maxFrames <= 40; maxFrames++) {
      for (let steps = 1; steps <= 3; steps++) {
        const plan = planCapture(Array.from({ length: steps }, () => 'blink'), maxFrames)
        if (plan) expect(plan.totalFrames).toBeLessThanOrEqual(Math.min(maxFrames, CAPTURE.hardMaxFrames))
      }
    }
  })

  it('returns null when the challenge cannot fit a frame per step', () => {
    expect(planCapture([], 30)).toBeNull()
    expect(planCapture(['blink', 'turn_left'], 1)).toBeNull()
    expect(planCapture(['blink'], Number.NaN)).toBeNull()
  })

  it('3 steps take 15 s, well inside the 80 s window', () => {
    expect(planCapture(['blink', 'turn_left', 'turn_right'], 30)!.durationMs).toBe(15000)
  })
})

describe('isChallengeFresh', () => {
  it('is fresh until 80 s after the fetch', () => {
    expect(isChallengeFresh(1000, 1000 + 79_999)).toBe(true)
    expect(isChallengeFresh(1000, 1000 + 80_000)).toBe(false)
  })
})
