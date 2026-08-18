// Service worker: the ONLY context allowed to call the backend. MV3 background
// fetch bypasses CORS for host_permissions origins, which is why /analyze runs
// here and never from the popup or a content script.
//
// The worker is ephemeral — Chrome evicts it between events — so it keeps NO
// state in module globals. Token, email, per-tab detection, and last result all
// live in chrome.storage.local and are re-read on each message.

import { ANALYZE_PATH, BACKEND_ORIGIN, CACHE_EMAIL_KEY, CACHE_TOKEN_KEY } from './config'
import type {
  AnalyzeResult,
  AuthState,
  DetectResult,
  ErrorCode,
  Message,
  ScrapeResult,
} from './types'

// --- storage helpers ------------------------------------------------------

async function getCached(): Promise<{ token: string | null; email: string | null }> {
  const got = await chrome.storage.local.get([CACHE_TOKEN_KEY, CACHE_EMAIL_KEY])
  return {
    token: (got[CACHE_TOKEN_KEY] as string | undefined) ?? null,
    email: (got[CACHE_EMAIL_KEY] as string | undefined) ?? null,
  }
}

async function setCached(token: string | null, email: string | null): Promise<void> {
  if (token) {
    await chrome.storage.local.set({ [CACHE_TOKEN_KEY]: token, [CACHE_EMAIL_KEY]: email })
  } else {
    await chrome.storage.local.remove([CACHE_TOKEN_KEY, CACHE_EMAIL_KEY])
  }
}

// --- on-demand injection --------------------------------------------------

// Inject the detector into the active tab. Idempotent — the content script's own
// sentinel ignores a second injection. Returns false on restricted pages
// (chrome://, Web Store, PDF viewer) where injection is not allowed.
async function ensureDetector(tabId: number): Promise<boolean> {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content-detector.js'],
    })
    return true
  } catch {
    return false
  }
}

async function detectActiveTab(): Promise<DetectResult> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab?.id || !(await ensureDetector(tab.id))) {
    return { injectable: false, source: null }
  }
  try {
    return await chrome.tabs.sendMessage<Message, DetectResult>(tab.id, {
      type: 'DETECT_TOS',
    })
  } catch {
    return { injectable: false, source: null }
  }
}

// --- scrape (with injection fallback) -------------------------------------

async function scrapeTab(tabId: number): Promise<ScrapeResult | null> {
  await ensureDetector(tabId) // the detector is injected on demand, not static
  try {
    return await chrome.tabs.sendMessage<Message, ScrapeResult>(tabId, {
      type: 'SCRAPE_TOS',
    })
  } catch {
    // Detector unreachable (e.g. injection was blocked) — last-resort body text.
    try {
      const [res] = await chrome.scripting.executeScript({
        target: { tabId },
        func: () => document.body?.innerText ?? '',
      })
      const text = (res?.result as string | undefined)?.trim() ?? ''
      return { text, url: '', truncated: false }
    } catch {
      return null
    }
  }
}

// --- analyze --------------------------------------------------------------

function fail(error: ErrorCode, message: string): AnalyzeResult {
  return { ok: false, error, message }
}

async function analyzeActiveTab(): Promise<AnalyzeResult> {
  const { token } = await getCached()
  if (!token) return fail('NOT_LOGGED_IN', 'Log in to ClearTerms to analyze.')

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab?.id) return fail('UNKNOWN', 'No active tab.')

  const scraped = await scrapeTab(tab.id)
  if (!scraped || !scraped.text.trim()) {
    return fail('NO_TEXT', "Couldn't find readable text on this page.")
  }

  let res: Response
  try {
    res = await fetch(`${BACKEND_ORIGIN}${ANALYZE_PATH}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ text: scraped.text, url: scraped.url || tab.url || null }),
    })
  } catch {
    return fail('NETWORK', 'ClearTerms backend is unreachable. Is it running?')
  }

  if (res.status === 401) {
    await setCached(null, null) // stale token — drop it and force re-login
    return fail('UNAUTHORIZED', 'Session expired. Please log in again.')
  }
  if (res.status === 413) {
    return fail('TOO_LARGE', 'This document is too large to analyze.')
  }
  if (!res.ok) {
    return fail('UNKNOWN', `Analysis failed (${res.status}).`)
  }

  const data = (await res.json()) as { verdict: string; analysis_id: number }
  return {
    ok: true,
    verdict: data.verdict,
    analysisId: data.analysis_id,
    truncated: scraped.truncated,
  }
}

// --- auth state -----------------------------------------------------------

async function getAuthState(): Promise<AuthState> {
  const { token, email } = await getCached()
  return { loggedIn: Boolean(token), email }
}

// --- message router -------------------------------------------------------

chrome.runtime.onMessage.addListener((msg: Message, _sender, sendResponse) => {
  switch (msg.type) {
    case 'AUTH_RELAY':
      void setCached(msg.token, msg.email)
      return // no response needed

    case 'GET_AUTH_STATE':
      getAuthState().then(sendResponse)
      return true // async response

    case 'DETECT_ACTIVE_TAB':
      detectActiveTab().then(sendResponse)
      return true // async response

    case 'ANALYZE_ACTIVE_TAB':
      analyzeActiveTab().then(sendResponse)
      return true // async response

    default:
      return
  }
})
