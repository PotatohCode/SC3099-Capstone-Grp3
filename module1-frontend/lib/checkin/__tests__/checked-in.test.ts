import { checkedInSessions, hasCheckIn } from '@/lib/checkin/checked-in'

describe('checkedInSessions', () => {
  const payload = (session_id: string) => ({ session_id, latitude: 1.3, longitude: 103.8, device_fingerprint: 'web-x' })

  it("separates history from this student's queued check-ins and ignores other students' queue items", () => {
    const result = checkedInSessions(
      [{ session_id: 'a' }],
      [
        { userId: 'u1', payload: payload('b') },
        { userId: 'u1', payload: payload('a') },
        { userId: 'u2', payload: payload('c') },
        { userId: undefined, payload: payload('d') },
      ],
      'u1'
    )
    expect(Array.from(result.submitted)).toEqual(['a'])
    expect(Array.from(result.queued)).toEqual(['b'])
    expect(['a', 'b', 'c', 'd'].map((id) => hasCheckIn(result, id))).toEqual([true, true, false, false])
  })

  it('ignores the queue when no student is signed in', () => {
    expect(Array.from(checkedInSessions([], [{ userId: 'u1', payload: payload('b') }], null).queued)).toEqual([])
  })
})
