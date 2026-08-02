import { useCallback, useState } from 'react'
import type { ReactNode } from 'react'
import { AuthContext } from './context'
import { clearAuth, getEmail, getToken, saveAuth } from './storage'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(getToken)
  const [email, setEmail] = useState<string | null>(getEmail)

  const login = useCallback((newToken: string, newEmail: string) => {
    saveAuth(newToken, newEmail)
    setToken(newToken)
    setEmail(newEmail)
  }, [])

  const logout = useCallback(() => {
    clearAuth()
    setToken(null)
    setEmail(null)
  }, [])

  return (
    <AuthContext.Provider value={{ token, email, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
