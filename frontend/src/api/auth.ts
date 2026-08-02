import { request, requestJson } from './client'
import type { TokenResponse } from './types'

export function signup(email: string, password: string): Promise<TokenResponse> {
  return requestJson<TokenResponse>('/auth/signup', 'POST', { email, password })
}

export function login(email: string, password: string): Promise<TokenResponse> {
  // OAuth2 password flow: form-encoded, email travels in the username field.
  const form = new URLSearchParams({ username: email, password })
  return request<TokenResponse>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form,
  })
}
