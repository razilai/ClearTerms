// localStorage persistence for the session. Kept outside AuthContext so the
// API client (non-React) can read the token and clear it on 401.

const TOKEN_KEY = 'clearterms.token'
const EMAIL_KEY = 'clearterms.email'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getEmail(): string | null {
  return localStorage.getItem(EMAIL_KEY)
}

export function saveAuth(token: string, email: string): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(EMAIL_KEY, email)
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(EMAIL_KEY)
}
