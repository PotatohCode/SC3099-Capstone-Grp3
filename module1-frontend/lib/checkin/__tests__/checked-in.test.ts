import { checkedInSessions, hasCheckIn } from '@/lib/checkin/checked-in'

describe('checkedInSessions', () => {
  it('marks only sessions found in the server history as checked in', () => {
    const result = checkedInSessions([{ session_id: 'a' }, { session_id: 'c' }])
    expect(Array.from(result.submitted)).toEqual(['a', 'c'])
    expect(['a', 'b', 'c'].map((id) => hasCheckIn(result, id))).toEqual([true, false, true])
  })
})
