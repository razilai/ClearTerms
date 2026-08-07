// Runs ONLY on the ClearTerms web-app origin (see manifest content_scripts).
// A content script shares the page's DOM + localStorage for that origin, which
// is the whole reason this exists: the service worker cannot read page
// localStorage, so we read the session here and relay it to the worker.

import { PAGE_EMAIL_KEY, PAGE_TOKEN_KEY } from './config'
import type { AuthRelayMsg } from './types'

function relay(): void {
  const msg: AuthRelayMsg = {
    type: 'AUTH_RELAY',
    token: localStorage.getItem(PAGE_TOKEN_KEY),
    email: localStorage.getItem(PAGE_EMAIL_KEY),
  }
  // Fire-and-forget; the worker caches into chrome.storage.local.
  chrome.runtime.sendMessage(msg).catch(() => {
    // Worker may be asleep/reloading — the next relay will retry.
  })
}

// Initial sync on page load.
relay()

// Live sync: `storage` fires in *other* tabs of the same origin when login /
// logout writes localStorage, so an open web-app tab keeps the extension current.
window.addEventListener('storage', (e) => {
  if (e.key === PAGE_TOKEN_KEY || e.key === PAGE_EMAIL_KEY || e.key === null) {
    relay()
  }
})

// The `storage` event does not fire in the same tab that made the write, so also
// re-relay when this tab regains focus (covers logging in on this very tab).
window.addEventListener('focus', relay)
