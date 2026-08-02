// Mirrors backend/app/agent/categories.py (ClauseCategory). The backend may
// grow the taxonomy; labelFor() falls back to title-casing unknown slugs so
// new categories render without a frontend change.

export const CATEGORY_ORDER = [
  'data_selling',
  'arbitration',
  'unilateral_changes',
  'content_licensing',
  'auto_renewal',
] as const

export const CATEGORY_LABELS: Record<string, string> = {
  data_selling: 'Data selling',
  arbitration: 'Forced arbitration',
  unilateral_changes: 'Unilateral changes',
  content_licensing: 'Content licensing',
  auto_renewal: 'Auto-renewal',
}

export const CATEGORY_DESCRIPTIONS: Record<string, string> = {
  data_selling: 'Your personal data may be sold or shared with third parties.',
  arbitration: 'Disputes go to private arbitration instead of court.',
  unilateral_changes: 'The company can change the terms without asking you.',
  content_licensing: 'The service claims broad rights over what you upload.',
  auto_renewal: 'Subscriptions renew and charge you automatically.',
}

export function labelFor(slug: string): string {
  const known = CATEGORY_LABELS[slug]
  if (known) return known
  const words = slug.replaceAll('_', ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

// Score scale: the backend leaves it TBD ("e.g. 0-2" in
// backend/app/agent/categories.py). Assume 0-2 and clamp so an out-of-range
// score never breaks the mark rendering.
export const SCORE_MAX = 2

export function clampScore(score: number): number {
  return Math.max(0, Math.min(SCORE_MAX, score))
}

// Preference weight: backend schema (backend/app/schemas/preferences.py) is an
// unconstrained float. UI assumption: 0.0-1.0, step 0.05, default 1.0 — every
// category counts fully until the user says otherwise.
export const DEFAULT_WEIGHT = 1
