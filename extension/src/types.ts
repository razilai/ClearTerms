// Shared message protocol across the three contexts (worker, content scripts,
// popup). A typo in a `type` string is the likeliest bug class here, so every
// message is a member of one discriminated union imported everywhere.

export type ErrorCode =
  | 'NOT_LOGGED_IN'
  | 'UNAUTHORIZED'
  | 'TOO_LARGE'
  | 'NETWORK'
  | 'NO_TEXT'
  | 'UNKNOWN'

// --- content-token -> background ---
export interface AuthRelayMsg {
  type: 'AUTH_RELAY'
  token: string | null
  email: string | null
}

// How the page was flagged: the page itself is a TOS ('page'), or it carries an
// "I agree to <terms>" checkbox linking to one ('agreement').
export type DetectionSource = 'page' | 'agreement'

// --- popup -> background ---
export interface GetAuthStateMsg {
  type: 'GET_AUTH_STATE'
}
// Popup open triggers on-demand detection of the active tab (injects the
// detector, then asks it what it found). Replaces the old passive per-page scan.
export interface DetectActiveTabMsg {
  type: 'DETECT_ACTIVE_TAB'
}
export interface AnalyzeActiveTabMsg {
  type: 'ANALYZE_ACTIVE_TAB'
}

// --- background -> content-detector ---
export interface DetectTosMsg {
  type: 'DETECT_TOS'
}
export interface ScrapeTosMsg {
  type: 'SCRAPE_TOS'
}

export type Message =
  | AuthRelayMsg
  | GetAuthStateMsg
  | DetectActiveTabMsg
  | AnalyzeActiveTabMsg
  | DetectTosMsg
  | ScrapeTosMsg

// --- responses ---
export interface AuthState {
  loggedIn: boolean
  email: string | null
}

// Result of on-demand detection. `injectable` is false on restricted pages
// (chrome://, Web Store, PDF viewer) where the detector can't be injected.
export interface DetectResult {
  injectable: boolean
  source: DetectionSource | null
}

export interface ScrapeResult {
  text: string
  url: string
  truncated: boolean
}

export type AnalyzeResult =
  | { ok: true; verdict: string; analysisId: number; truncated: boolean }
  | { ok: false; error: ErrorCode; message: string }
