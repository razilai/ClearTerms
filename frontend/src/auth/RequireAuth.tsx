import { useEffect } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from './useAuth'

// Client-side expiry check so a stale token in localStorage doesn't let the
// guard render a protected page that only fails on the first API 401. Catches
// expiry, not server-side revocation (that still surfaces as a 401 → /login).
function isExpired(token: string): boolean {
  try {
    const { exp } = JSON.parse(atob(token.split('.')[1]))
    return typeof exp === 'number' && exp * 1000 < Date.now()
  } catch {
    return true // malformed → treat as invalid
  }
}

export function RequireAuth() {
  const { token, logout } = useAuth()
  const expired = !!token && isExpired(token)

  // Clear the stale token as a side effect (can't mutate state during render).
  useEffect(() => {
    if (expired) logout()
  }, [expired, logout])

  if (!token || expired) return <Navigate to="/login" replace />
  return <Outlet />
}
