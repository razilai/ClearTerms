// Runs on every page (broad match). Jobs:
//   (1) auto-detect whether this page is a Terms-of-Service / legal agreement,
//       OR carries an "I agree to <terms>" checkbox linking to one, and tell the
//       worker to raise the badge;
//   (2) on demand (SCRAPE_TOS from the worker) return the readable text — from a
//       linked terms doc if an agreement checkbox was found, else from the page.
// It never talks to the backend and never touches the token.

import { MAX_ANALYZE_BYTES } from './config'
import type { DetectionSource, Message, ScrapeResult } from './types'

// Same-origin terms links found next to an agreement checkbox. Kept in module
// scope (content scripts live as long as the page) so SCRAPE_TOS can use them.
let agreementLinks: string[] = []

// --- page-is-TOS detection ------------------------------------------------

const URL_PATTERNS =
  /\/(terms|tos|terms-of-service|terms-and-conditions|terms-of-use|eula|legal|conditions|user-agreement)\b/i

const HEADING_PATTERNS =
  /terms of (service|use)|terms (and|&) conditions|end user license|user agreement|conditions of use/i

// Weaker, high-frequency legal markers used for a density signal on long docs.
const LEGAL_MARKERS = [
  'you agree',
  'hereby',
  'limitation of liability',
  'governing law',
  'arbitration',
  'indemnif',
  'warrant',
  'we may',
  'terminate',
  'privacy policy',
  'intellectual property',
]

function pageIsTos(): boolean {
  let score = 0

  if (URL_PATTERNS.test(location.pathname) || HEADING_PATTERNS.test(document.title)) {
    score += 2
  }

  for (const h of document.querySelectorAll('h1, h2')) {
    if (HEADING_PATTERNS.test(h.textContent ?? '')) {
      score += 2
      break
    }
  }

  const bodyText = document.body?.innerText ?? ''
  if (bodyText.split(/\s+/).length > 800) {
    const lower = bodyText.toLowerCase()
    const hits = LEGAL_MARKERS.reduce((n, m) => n + (lower.includes(m) ? 1 : 0), 0)
    if (hits >= 4) score += 1
  }

  return score >= 2
}

// --- agreement-checkbox detection -----------------------------------------

const AGREE_PATTERN = /\b(agree|accept|i have read|consent|acknowledge)\b/i
const TERMS_LINK_PATTERN = /terms|tos|conditions|eula|agreement|policy|legal/i

// The text/container that labels a checkbox: its <label for>, an ancestor
// <label>, or the nearest block-ish ancestor that carries text + a link.
function labelFor(box: HTMLInputElement): HTMLElement | null {
  if (box.id) {
    const forLabel = document.querySelector<HTMLElement>(`label[for="${CSS.escape(box.id)}"]`)
    if (forLabel) return forLabel
  }
  const ancestorLabel = box.closest('label')
  if (ancestorLabel) return ancestorLabel as HTMLElement
  // Fallback: walk up a few levels to a container that has both text and a link.
  let el: HTMLElement | null = box.parentElement
  for (let i = 0; i < 3 && el; i++, el = el.parentElement) {
    if (el.querySelector('a[href]') && (el.textContent ?? '').trim().length > 0) return el
  }
  return null
}

function sameOrigin(href: string): string | null {
  try {
    const u = new URL(href, location.href)
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null
    return u.origin === location.origin ? u.href : null
  } catch {
    return null
  }
}

// Collect same-origin terms links from "agree" checkboxes. Cross-origin links
// are skipped (we can't fetch them without broad host permissions).
function findAgreementLinks(): string[] {
  const links = new Set<string>()
  for (const box of document.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')) {
    const label = labelFor(box)
    if (!label || !AGREE_PATTERN.test(label.textContent ?? '')) continue
    for (const a of label.querySelectorAll<HTMLAnchorElement>('a[href]')) {
      const text = `${a.textContent ?? ''} ${a.getAttribute('href') ?? ''}`
      if (!TERMS_LINK_PATTERN.test(text)) continue
      const href = sameOrigin(a.href)
      if (href) links.add(href)
    }
  }
  return [...links].slice(0, 3) // cap: don't fan out fetches unbounded
}

// --- run detection --------------------------------------------------------

function runDetection(): void {
  agreementLinks = findAgreementLinks()
  let source: DetectionSource | null = null
  if (pageIsTos()) source = 'page'
  else if (agreementLinks.length > 0) source = 'agreement'
  if (!source) return

  const msg: Message = {
    type: 'TOS_DETECTED',
    url: location.href,
    title: document.title,
    confidence: source === 'page' ? 2 : 1,
    source,
  }
  chrome.runtime.sendMessage(msg).catch(() => {})
}

runDetection()
// Many legal pages / forms are client-routed; re-check on SPA navigation.
window.addEventListener('popstate', runDetection)
window.addEventListener('hashchange', runDetection)

// --- text extraction ------------------------------------------------------

const CONTENT_SELECTORS = ['main', 'article', '[role="main"]', '#content', '.content', '.legal', '.terms']
const NOISE_SELECTORS = 'script, style, noscript, nav, header, footer, aside'

// Live page: innerText is rendered, so it already omits hidden nodes and reads best.
function extractLivePage(): string {
  for (const sel of CONTENT_SELECTORS) {
    const text = document.querySelector<HTMLElement>(sel)?.innerText?.trim()
    if (text && text.length > 200) return text
  }
  let best = ''
  for (const el of document.querySelectorAll<HTMLElement>('div, section, article')) {
    if (el.closest('nav, header, footer, aside')) continue
    if (el.innerText.length > best.length) best = el.innerText
  }
  if (best.trim().length > 200) return best.trim()
  return document.body?.innerText?.trim() ?? ''
}

// Fetched-and-parsed doc: it isn't rendered, so innerText is empty — strip noise
// nodes and read textContent instead.
function extractParsed(doc: Document): string {
  doc.querySelectorAll(NOISE_SELECTORS).forEach((n) => n.remove())
  for (const sel of CONTENT_SELECTORS) {
    const text = doc.querySelector<HTMLElement>(sel)?.textContent?.trim()
    if (text && text.length > 200) return text
  }
  return doc.body?.textContent?.trim() ?? ''
}

function normalize(text: string): string {
  return text.replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim()
}

// Truncate by *bytes* (UTF-8), not chars, so multibyte content stays valid and
// we never exceed the backend limit.
function truncateBytes(text: string): { text: string; truncated: boolean } {
  const encoder = new TextEncoder()
  if (encoder.encode(text).length <= MAX_ANALYZE_BYTES) return { text, truncated: false }
  let lo = 0
  let hi = text.length
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2)
    if (encoder.encode(text.slice(0, mid)).length <= MAX_ANALYZE_BYTES) lo = mid
    else hi = mid - 1
  }
  return { text: text.slice(0, lo) + '\n\n…[truncated]', truncated: true }
}

// Fetch each same-origin agreement link, parse to a Document, extract its text,
// and join. Same-origin means no CORS and no extra host permission needed.
async function scrapeAgreementLinks(): Promise<{ text: string; url: string }> {
  const parts: string[] = []
  for (const link of agreementLinks) {
    try {
      const res = await fetch(link, { credentials: 'include' })
      if (!res.ok) continue
      const doc = new DOMParser().parseFromString(await res.text(), 'text/html')
      const text = extractParsed(doc)
      if (text.length > 200) parts.push(text)
    } catch {
      // Skip unreachable/unparseable links; others may still succeed.
    }
  }
  // Record the primary link as the source url so history shows the terms page.
  return { text: parts.join('\n\n---\n\n'), url: agreementLinks[0] ?? location.href }
}

async function scrape(): Promise<ScrapeResult> {
  const raw =
    agreementLinks.length > 0
      ? await scrapeAgreementLinks()
      : { text: extractLivePage(), url: location.href }
  const { text, truncated } = truncateBytes(normalize(raw.text))
  return { text, url: raw.url, truncated }
}

// --- message handling -----------------------------------------------------

chrome.runtime.onMessage.addListener((msg: Message, _sender, sendResponse) => {
  if (msg.type === 'SCRAPE_TOS') {
    // Async (agreement links are fetched) — return true to keep the channel open.
    scrape().then(sendResponse)
    return true
  }
  return
})
