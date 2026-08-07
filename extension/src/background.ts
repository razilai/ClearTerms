// Service worker: the ONLY context allowed to call the backend. MV3 background
// fetch bypasses CORS for host_permissions origins, which is why /analyze runs
// here and never from the popup or a content script.
//
// The worker is ephemeral — Chrome evicts it between events — so it keeps NO
// state in module globals. Token, email, per-tab detection, and last result all
// live in chrome.storage.local and are re-read on each message.

import {
  ANALYZE_PATH,
  BACKEND_ORIGIN,
  BADGE_COLOR,
  BADGE_TEXT,
  CACHE_EMAIL_KEY,
  CACHE_TOKEN_KEY,
} from './config'
import type {
  AnalyzeResult,
  AuthState,
  DetectionSource,
  ErrorCode,
  Message,
  ScrapeResult,
} from './types'

// Per-tab detection source, keyed so a tab's badge state survives worker eviction.
const detectedKey = (tabId: number) => `ct_detected_${tabId}`

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

// --- badge ----------------------------------------------------------------

async function setBadge(tabId: number, source: DetectionSource | null): Promise<void> {
  await chrome.action.setBadgeBackgroundColor({ color: BADGE_COLOR })
  await chrome.action.setBadgeText({ tabId, text: source ? BADGE_TEXT : '' })
  if (source) await chrome.storage.local.set({ [detectedKey(tabId)]: source })
  else await chrome.storage.local.remove(detectedKey(tabId))
}

// Clear the badge/flag when a tab navigates away or closes.
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url) void setBadge(tabId, null)
})
chrome.tabs.onRemoved.addListener((tabId) => {
  void chrome.storage.local.remove(detectedKey(tabId))
})

// --- scrape (with injection fallback) -------------------------------------

async function scrapeTab(tabId: number): Promise<ScrapeResult | null> {
  try {
    // Fast path: the detector content script is already present.
    return await chrome.tabs.sendMessage<Message, ScrapeResult>(tabId, {
      type: 'SCRAPE_TOS',
    })
  } catch {
    // Page predates install (no content script) — inject and grab body text.
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
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  let detection: DetectionSource | null = null
  if (tab?.id) {
    const got = await chrome.storage.local.get(detectedKey(tab.id))
    detection = (got[detectedKey(tab.id)] as DetectionSource | undefined) ?? null
  }
  return { loggedIn: Boolean(token), email, detection }
}

// --- message router -------------------------------------------------------

chrome.runtime.onMessage.addListener((msg: Message, sender, sendResponse) => {
  switch (msg.type) {
    case 'AUTH_RELAY':
      void setCached(msg.token, msg.email)
      return // no response needed

    case 'TOS_DETECTED':
      if (sender.tab?.id) void setBadge(sender.tab.id, msg.source)
      return

    case 'GET_AUTH_STATE':
      getAuthState().then(sendResponse)
      return true // async response

    case 'ANALYZE_ACTIVE_TAB':
      analyzeActiveTab().then(sendResponse)
      return true // async response

    default:
      return
  }
})
