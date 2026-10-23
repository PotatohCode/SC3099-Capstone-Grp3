import { CAPTURE, isChallengeFresh, planCapture, promptFor } from '@/lib/liveness/challenge'

describe('promptFor', () => {
  it('prompts the three known actions and a generic one for unknown actions', () => {
    expect(promptFor('blink')).toBe('Blink a few times')
    expect(promptFor('turn_left')).toBe('Slowly turn your head to your left')
    expect(promptFor('turn_right')).toBe('Slowly turn your head to your right')
    expect(promptFor('nod_twice')).toBe('Please do this now: nod twice')
  })
})

describe('planCapture', () => {
  it('plans 8 frames per step at 5 fps with countdown, lead-in and gap', () => {
    const plan = planCapture(['blink', 'turn_left'], 30)!
    expect(plan.totalFrames).toBe(16)
    expect(plan.steps[0].startMs).toBe(3000)
    expect(plan.steps[0].frameOffsetsMs).toEqual([3500, 3700, 3900, 4100, 4300, 4500, 4700, 4900])
    expect(plan.steps[1].startMs).toBe(5400)
    expect(plan.steps[1].frameOffsetsMs[0]).toBe(5900)
    expect(plan.durationMs).toBe(7300)
  })

  it.each([
    [1, 30, 8, 8],
    [2, 30, 8, 16],
    [3, 30, 8, 24],
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

  it('3 steps take 9.7 s, well inside the 80 s window', () => {
    expect(planCapture(['blink', 'turn_left', 'turn_right'], 30)!.durationMs).toBe(9700)
  })
})

describe('isChallengeFresh', () => {
  it('is fresh until 80 s after the fetch', () => {
    expect(isChallengeFresh(1000, 1000 + 79_999)).toBe(true)
    expect(isChallengeFresh(1000, 1000 + 80_000)).toBe(false)
  })
})
