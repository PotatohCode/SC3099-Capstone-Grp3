'use client'

/**
 * Task 1.6 / Component tree Section 2.1: "AuthContext (JWT token state, auto-refresh logic)"
 * Decision 2 (Section 9): "State Management: React Context (AuthContext + CheckInContext)"
 *
 * Also wires in Task 1.7 (device registration on first login): after a successful
 * login we generate/reuse a device fingerprint and call POST /devices/register so the
 * fingerprint is bound to the account before any check-in is attempted.
 */

import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useRouter } from 'next/navigation'
import * as authService from '@/lib/services/auth.service'
import { registerDevice } from '@/lib/services/device.service'
import {
  detectPlatform,
  getOrCreateDeviceFingerprint,
} from '@/lib/utils/device-fingerprint'
import { extractErrorMessage } from '@/lib/utils/http-client'
import {
  clearTokens,
  getAccessToken,
  hasAccessToken,
  setTokens,
} from '@/lib/utils/token-storage'
import type { LoginRequest, RegisterRequest, User } from '@/lib/types'

interface AuthContextValue {
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  login: (payload: LoginRequest) => Promise<void>
  register: (payload: RegisterRequest) => Promise<User>
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)

const DEVICE_REGISTERED_FLAG = 'saiv_device_registered'

async function registerDeviceOnce(): Promise<void> {
  if (typeof window === 'undefined') return
  if (window.sessionStorage.getItem(DEVICE_REGISTERED_FLAG) === 'true') return
  try {
    const fingerprint = getOrCreateDeviceFingerprint()
    await registerDevice({
      device_fingerprint: fingerprint,
      device_name: 'Web Browser',
      platform: detectPlatform(),
    })
    window.sessionStorage.setItem(DEVICE_REGISTERED_FLAG, 'true')
  } catch {
    // Device registration is best-effort; do not block login if it fails
    // (e.g. device already registered, or backend temporarily unavailable).
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const router = useRouter()

  const logout = useCallback(() => {
    clearTokens()
    setUser(null)
    if (typeof window !== 'undefined') {
      window.sessionStorage.removeItem(DEVICE_REGISTERED_FLAG)
    }
    router.push('/auth/login')
  }, [router])

  // Bootstrap: if an access token already exists in sessionStorage (e.g. page refresh),
  // fetch the current user to rehydrate context state.
  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      if (!hasAccessToken()) {
        setIsLoading(false)
        return
      }
      try {
        const currentUser = await authService.getCurrentUser()
        if (!cancelled) setUser(currentUser)
      } catch {
        if (!cancelled) clearTokens()
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    bootstrap()
    return () => {
      cancelled = true
    }
  }, [])

  // http-client dispatches this when a silent refresh fails (Section 2.2: "Failure:
  // Redirect to /auth/login").
  useEffect(() => {
    function handleExpired() {
      setUser(null)
    }
    window.addEventListener('saiv:auth-expired', handleExpired)
    return () => window.removeEventListener('saiv:auth-expired', handleExpired)
  }, [])

  const login = useCallback(async (payload: LoginRequest) => {
    try {
      const response = await authService.login(payload)
      setTokens(response.access_token, response.refresh_token)
      setUser(response.user)
      await registerDeviceOnce()
    } catch (error) {
      throw new Error(extractErrorMessage(error, 'Login failed. Check your credentials.'))
    }
  }, [])

  const register = useCallback(async (payload: RegisterRequest) => {
    try {
      return await authService.register(payload)
    } catch (error) {
      throw new Error(extractErrorMessage(error, 'Registration failed.'))
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      isAuthenticated: !!user && !!getAccessToken(),
      login,
      register,
      logout,
    }),
    [user, isLoading, login, register, logout]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
