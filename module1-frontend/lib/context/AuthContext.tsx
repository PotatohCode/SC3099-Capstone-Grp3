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
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useRouter } from 'next/navigation'
import * as authService from '@/lib/services/auth.service'
import { registerCurrentDevice } from '@/lib/services/device.service'
import { clearOfflineQueue } from '@/lib/services/offline.service'
import { loginErrorMessage } from '@/lib/utils/api-error'
import { FACE_PROMPT_DISMISSED_KEY, reauthErrorMessage } from '@/lib/face/enrollment'
import { recordConsent, type ConsentType } from '@/lib/utils/consent-tracker'
import {
  clearTokens,
  getAccessToken,
  hasAccessToken,
  setTokens,
} from '@/lib/utils/token-storage'
import type { LoginRequest, User } from '@/lib/types'

interface AuthContextValue {
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  login: (payload: LoginRequest) => Promise<void>
  logout: () => Promise<void>
  saveConsent: (type: ConsentType, granted: boolean) => Promise<boolean>
  reauthenticate: (password: string) => Promise<void>
  refreshUser: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)

const DEVICE_REGISTERED_FLAG = 'saiv_device_registered'

async function registerDeviceOnce(): Promise<void> {
  if (typeof window === 'undefined') return
  if (window.sessionStorage.getItem(DEVICE_REGISTERED_FLAG) === 'true') return
  try {
    await registerCurrentDevice()
    window.sessionStorage.setItem(DEVICE_REGISTERED_FLAG, 'true')
  } catch {
    // Device registration is best-effort; do not block login if it fails
    // (e.g. device already registered, or backend temporarily unavailable).
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const userRef = useRef<User | null>(null)
  userRef.current = user
  const router = useRouter()

  const logout = useCallback(async () => {
    await clearOfflineQueue().catch(() => undefined)
    await authService.logoutAndClear()
    setUser(null)
    if (typeof window !== 'undefined') {
      window.sessionStorage.removeItem(DEVICE_REGISTERED_FLAG)
      window.sessionStorage.removeItem(FACE_PROMPT_DISMISSED_KEY)
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
      window.sessionStorage.removeItem(FACE_PROMPT_DISMISSED_KEY)
      setUser(response.user)
      await registerDeviceOnce()
    } catch (error) {
      throw new Error(loginErrorMessage(error))
    }
  }, [])

  const saveConsent = useCallback(async (type: ConsentType, granted: boolean) => {
    const current = userRef.current
    const serverValue = type === 'camera' ? current?.camera_consent : current?.geolocation_consent
    const updated = await recordConsent(type, granted, serverValue)
    if (updated) setUser(updated)
    const saved = updated ? (type === 'camera' ? updated.camera_consent : updated.geolocation_consent) : serverValue
    return saved === granted
  }, [])

  const reauthenticate = useCallback(async (password: string) => {
    const current = userRef.current
    if (!current) throw new Error('You are not signed in.')
    let response
    try {
      response = await authService.login({ email: current.email, password })
    } catch (error) {
      throw new Error(reauthErrorMessage(error))
    }
    if (response.user?.id !== current.id) throw new Error('Password check failed. Please sign in again.')
    setUser(response.user)
  }, [])

  const refreshUser = useCallback(async () => {
    setUser(await authService.getCurrentUser())
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      isAuthenticated: !!user && !!getAccessToken(),
      login,
      logout,
      saveConsent,
      reauthenticate,
      refreshUser,
    }),
    [user, isLoading, login, logout, saveConsent, reauthenticate, refreshUser]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
