// Single source of truth for the JS side. NOTE: the origins here are duplicated
// in public/manifest.json (host_permissions + content_scripts matches) because
// the manifest can't read JS constants — keep the two in sync, and add prod
// origins to BOTH when deploying.

export const BACKEND_ORIGIN = 'http://localhost:8000'
export const WEB_ORIGIN = 'http://localhost:5173'

export const LOGIN_PATH = '/login'
export const ANALYZE_PATH = '/analyze'
export const HISTORY_URL = `${WEB_ORIGIN}/history`
export const LOGIN_URL = `${WEB_ORIGIN}${LOGIN_PATH}`

export function analysisDetailUrl(id: number): string {
  return `${WEB_ORIGIN}/analyses/${id}`
}

// Mirrors frontend/src/auth/storage.ts — the web app writes the session here and
// content-token.ts reads it back out of the page's localStorage.
export const PAGE_TOKEN_KEY = 'clearterms.token'
export const PAGE_EMAIL_KEY = 'clearterms.email'

// Keys the extension caches under in chrome.storage.local (namespaced separately
// from the page keys above to avoid confusion).
export const CACHE_TOKEN_KEY = 'ct_token'
export const CACHE_EMAIL_KEY = 'ct_email'

// Margin under the backend's max_analyze_bytes (1_000_000) so a slightly-off
// byte estimate never trips the 413.
export const MAX_ANALYZE_BYTES = 950_000
