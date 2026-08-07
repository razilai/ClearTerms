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

// --- content-detector -> background ---
export interface TosDetectedMsg {
  type: 'TOS_DETECTED'
  url: string
  title: string
  confidence: number
  source: DetectionSource
}

// --- popup -> background ---
export interface GetAuthStateMsg {
  type: 'GET_AUTH_STATE'
}
export interface AnalyzeActiveTabMsg {
  type: 'ANALYZE_ACTIVE_TAB'
}

// --- background -> content-detector ---
export interface ScrapeTosMsg {
  type: 'SCRAPE_TOS'
}

export type Message =
  | AuthRelayMsg
  | TosDetectedMsg
  | GetAuthStateMsg
  | AnalyzeActiveTabMsg
  | ScrapeTosMsg

// --- responses ---
export interface AuthState {
  loggedIn: boolean
  email: string | null
  // What the worker flagged on the active tab, or null if nothing.
  detection: DetectionSource | null
}

export interface ScrapeResult {
  text: string
  url: string
  truncated: boolean
}

export type AnalyzeResult =
  | { ok: true; verdict: string; analysisId: number; truncated: boolean }
  | { ok: false; error: ErrorCode; message: string }
