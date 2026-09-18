import { useContext } from 'react'
import { CheckInContext } from '@/lib/context/CheckInContext'

export function useCheckIn() {
  const context = useContext(CheckInContext)
  if (!context) {
    throw new Error('useCheckIn must be used within a CheckInProvider')
  }
  return context
}
