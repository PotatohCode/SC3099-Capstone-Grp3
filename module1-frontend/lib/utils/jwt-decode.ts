/**
 * Component tree Section 2.1: "jwt-decode.ts [Parse JWT claims]"
 *
 * Decodes the (already-verified-by-backend) JWT payload client-side purely to read
 * non-sensitive claims such as `exp`/`role` for UX purposes (e.g. proactive refresh
 * scheduling). This performs NO signature verification - it must never be used as a
 * security boundary, only as a convenience.
 */

export interface JwtClaims {
  sub: string
  email?: string
  role?: string
  exp?: number
  iat?: number
  [key: string]: unknown
}

export function decodeJwt(token: string): JwtClaims | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null

    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = payload.padEnd(payload.length + ((4 - (payload.length % 4)) % 4), '=')
    const decoded = typeof window !== 'undefined' ? window.atob(padded) : atob(padded)
    const json = decodeURIComponent(
      decoded
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    )
    return JSON.parse(json) as JwtClaims
  } catch {
    return null
  }
}

/** Returns true if the token's `exp` claim is in the past (or unparsable). */
export function isTokenExpired(token: string): boolean {
  const claims = decodeJwt(token)
  if (!claims || !claims.exp) return true
  const nowSeconds = Date.now() / 1000
  return claims.exp <= nowSeconds
}

/** Milliseconds until expiry (negative if already expired, null if unknown). */
export function msUntilExpiry(token: string): number | null {
  const claims = decodeJwt(token)
  if (!claims || !claims.exp) return null
  return claims.exp * 1000 - Date.now()
}
