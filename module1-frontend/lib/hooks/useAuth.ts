/**
 * Component tree Section 2.1: "useAuth() [Auth state + refresh]"
 */

import { useContext } from 'react'
import { AuthContext } from '@/lib/context/AuthContext'

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
