import { clearProgress, PROGRESS_MAX_AGE_MS, readProgress, saveProgress } from '@/lib/checkin/progress'

describe('check-in progress', () => {
  it('is saved per student and cleared on request', () => {
    saveProgress('u1', 's1', 1000)
    saveProgress('u2', 's9', 1000)
    expect(readProgress('u1', 2000)).toBe('s1')
    expect(readProgress('u2', 2000)).toBe('s9')
    clearProgress('u1')
    expect(readProgress('u1', 2000)).toBeNull()
    expect(readProgress('u2', 2000)).toBe('s9')
  })

  it('expires after 12 hours and ignores missing users or corrupt data', () => {
    saveProgress('u1', 's1', 0)
    expect(readProgress('u1', PROGRESS_MAX_AGE_MS)).toBe('s1')
    expect(readProgress('u1', PROGRESS_MAX_AGE_MS + 1)).toBeNull()
    saveProgress(null, 's1')
    expect(readProgress(null)).toBeNull()
    window.localStorage.setItem('saiv_checkin_progress:u3', '{not json')
    expect(readProgress('u3')).toBeNull()
  })
})
