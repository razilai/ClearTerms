// Popup UI. Holds no token itself — it only asks the worker for auth state and
// analysis results, and opens web-app tabs for login / result deep links.

import { HISTORY_URL, LOGIN_URL, analysisDetailUrl } from './config'
import type { AnalyzeResult, AuthState, DetectResult, Message } from './types'

const root = document.getElementById('root') as HTMLElement
const emailEl = document.getElementById('email') as HTMLElement

function send<R>(msg: Message): Promise<R> {
  return chrome.runtime.sendMessage(msg) as Promise<R>
}

function clear(): void {
  root.replaceChildren()
  emailEl.textContent = ''
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: Partial<HTMLElementTagNameMap[K]> = {},
  children: (Node | string)[] = [],
): HTMLElementTagNameMap[K] {
  const node = Object.assign(document.createElement(tag), props)
  for (const c of children) node.append(c)
  return node
}

function openTab(url: string): void {
  void chrome.tabs.create({ url })
  window.close()
}

// --- states ---------------------------------------------------------------

function renderLoggedOut(note?: string): void {
  clear()
  const btn = el('button', { className: 'btn-primary', textContent: 'Log in' })
  btn.addEventListener('click', () => openTab(LOGIN_URL))
  root.append(
    el('p', { className: 'muted', textContent: note ?? 'Log in to ClearTerms to analyze this page.' }),
    btn,
  )
}

function renderIdle(email: string | null, detect: DetectResult): void {
  clear()
  emailEl.textContent = email ?? ''

  // Restricted pages (chrome://, Web Store, PDF viewer) can't be injected, so
  // there's nothing to scrape — say so instead of offering a dead button.
  if (!detect.injectable) {
    root.append(el('p', { className: 'muted', textContent: "Can't analyze this page." }))
    return
  }

  const status =
    detect.source === 'agreement'
      ? 'Agreement checkbox detected — analyze the linked terms.'
      : detect.source === 'page'
        ? 'Terms of Service detected on this page.'
        : 'No terms detected — you can still analyze.'
  const label = detect.source === 'agreement' ? 'Analyze linked terms' : 'Analyze full page'
  const btn = el('button', { className: 'btn-primary', textContent: label })
  btn.addEventListener('click', () => void runAnalyze())
  root.append(el('p', { className: 'status', textContent: status }), btn)
}

function renderAnalyzing(): void {
  clear()
  root.append(
    el('div', { className: 'verdict' }, [el('span', { className: 'spinner' }), 'Analyzing…']),
  )
}

// Map the backend verdict string to a traffic-light dot. Verdict wording is
// backend-owned; match loosely on thumbs/keywords and fall back to neutral.
function verdictClass(verdict: string): string {
  const v = verdict.toLowerCase()
  if (v.includes('down') || v.includes('reject') || v.includes('avoid')) return 'red'
  if (v.includes('up') || v.includes('ok') || v.includes('accept') || v.includes('clear')) return 'green'
  return 'yellow'
}

function renderResult(res: Extract<AnalyzeResult, { ok: true }>): void {
  clear()
  const links = el('div', { className: 'links' })
  const detail = el('a', { textContent: 'View full analysis →', href: '#' })
  detail.addEventListener('click', (e) => {
    e.preventDefault()
    openTab(analysisDetailUrl(res.analysisId))
  })
  const history = el('a', { textContent: 'Open history', href: '#' })
  history.addEventListener('click', (e) => {
    e.preventDefault()
    openTab(HISTORY_URL)
  })
  links.append(detail, history)

  root.append(
    el('div', { className: 'verdict' }, [
      el('span', { className: `dot ${verdictClass(res.verdict)}` }),
      res.verdict,
    ]),
    links,
  )
  if (res.truncated) {
    root.append(
      el('p', { className: 'muted', textContent: 'Page was long; analyzed the first part.' }),
    )
  }
}

function renderError(res: Extract<AnalyzeResult, { ok: false }>): void {
  if (res.error === 'NOT_LOGGED_IN' || res.error === 'UNAUTHORIZED') {
    renderLoggedOut(res.message)
    return
  }
  clear()
  const retry = el('button', { className: 'btn-secondary', textContent: 'Try again' })
  retry.addEventListener('click', () => void runAnalyze())
  root.append(el('p', { className: 'error', textContent: res.message }), retry)
}

// --- flows -----------------------------------------------------------------

async function runAnalyze(): Promise<void> {
  renderAnalyzing()
  const res = await send<AnalyzeResult>({ type: 'ANALYZE_ACTIVE_TAB' })
  if (res.ok) renderResult(res)
  else renderError(res)
}

async function init(): Promise<void> {
  const state = await send<AuthState>({ type: 'GET_AUTH_STATE' })
  if (!state.loggedIn) {
    renderLoggedOut()
    return
  }
  // Detection is on-demand: injected into the active tab only now, on popup open.
  const detect = await send<DetectResult>({ type: 'DETECT_ACTIVE_TAB' })
  renderIdle(state.email, detect)
}

void init()
