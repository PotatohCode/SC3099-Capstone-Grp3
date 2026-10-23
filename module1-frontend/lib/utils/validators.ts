/**
 * Component tree Section 2.1: "validators.ts [Email, password, coordinates validation]"
 * Task 1.1: "Implement client-side validation: email format, password >= 8 chars"
 */

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function isValidEmail(email: string): boolean {
  return EMAIL_REGEX.test(email.trim())
}

/** docs/SECURITY-REQUIREMENTS.md: latitude -90..90, longitude -180..180 */
export function isValidCoordinate(latitude: number, longitude: number): boolean {
  return (
    Number.isFinite(latitude) &&
    Number.isFinite(longitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    longitude >= -180 &&
    longitude <= 180
  )
}

/** Basic sanitizer to strip characters that enable HTML/script injection in text fields. */
export function sanitizeText(input: string): string {
  return input.replace(/[<>]/g, '').trim()
}

export interface FieldError {
  field: string
  message: string
}

export function validateLoginForm(email: string, password: string): FieldError[] {
  const errors: FieldError[] = []
  if (!isValidEmail(email)) {
    errors.push({ field: 'email', message: 'Enter a valid email address.' })
  }
  if (!password) {
    errors.push({ field: 'password', message: 'Password is required.' })
  }
  return errors
}
