import { createContext } from 'react'

export interface AuthState {
  token: string | null
  email: string | null
  login: (token: string, email: string) => void
  logout: () => void
}

export const AuthContext = createContext<AuthState | null>(null)
