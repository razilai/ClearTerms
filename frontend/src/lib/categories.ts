import type { PreferenceItem } from '../api/types'

// Mirrors the ClauseCategory taxonomy in backend/app/schemas/analysis.py, using
// the display_name/description product voice from
// backend/app/agent/prompts/categories.toml. Order matches the backend enum
// (the order densify emits scores in). The backend may grow the taxonomy;
// labelFor() falls back to title-casing unknown slugs so a new category renders
// without a frontend change.

export const CATEGORY_ORDER = [
  'unilateral_changes',
  'arbitration',
  'liability',
  'content_licensing',
  'data_collection',
  'termination',
] as const

export const CATEGORY_LABELS: Record<string, string> = {
  unilateral_changes: 'Changes',
  arbitration: 'Arbitration',
  liability: 'Accountability',
  content_licensing: 'Content Grab',
  data_collection: 'Data Harvesting',
  termination: 'Exit Terms',
}

export const CATEGORY_DESCRIPTIONS: Record<string, string> = {
  unilateral_changes:
    'The company can rewrite the terms, fees, or features at any time — continued use counts as consent.',
  arbitration:
    'Disputes are forced into private arbitration, waiving your right to court or class actions.',
  liability:
    'The company disclaims responsibility for damages and may shift its own legal costs onto you.',
  content_licensing:
    'Content you upload can be licensed broadly — commercialized or used to train AI.',
  data_collection:
    'Behavioral data is collected, profiled, and shared or sold to third parties.',
  termination:
    'The company can cut off your account and keep paid balances, while your own exit is kept narrow.',
}

export function labelFor(slug: string): string {
  const known = CATEGORY_LABELS[slug]
  if (known) return known
  const words = slug.replaceAll('_', ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

// Score scale: backend/app/agent/categories.py defines a 0-2 scale
// (SCORE_ABSENT..SCORE_AGGRESSIVE). Rendered as a stoplight: green when the
// category is absent, yellow for standard terms, red for aggressive ones.
export const SCORE_MAX = 2

// Mantine color key + label word for each score. Clamp so an out-of-range
// score can never break the mark rendering (unknown scores land on red).
const STOPLIGHT: Record<number, { color: string; label: string }> = {
  0: { color: 'ok', label: 'Clear' },
  1: { color: 'highlight', label: 'Standard' },
  2: { color: 'redline', label: 'Aggressive' },
}

export function stoplightFor(score: number): { color: string; label: string } {
  const clamped = Math.max(0, Math.min(SCORE_MAX, Math.round(score)))
  return STOPLIGHT[clamped]
}

// Preferences are a binary checklist (backend/app/schemas/preferences.py).
// A category with no saved row is on, mirroring DEFAULT_ENABLED in
// backend/app/services/preferences.py — everything counts until the user says
// otherwise.
export const DEFAULT_ENABLED = true

// The categories a report should show, given the user's saved preferences.
// Unchecked categories are hidden from the breakdown and, on the backend, are
// skipped by compute_verdict. Preferences that have not loaded yet (undefined)
// hide nothing, so a report never flickers rows out from under the reader.
export function enabledCategories(
  items: PreferenceItem[] | undefined,
): (category: string) => boolean {
  if (items === undefined) return () => true
  const saved = new Map(items.map((item) => [item.category, item.enabled]))
  return (category) => saved.get(category) ?? DEFAULT_ENABLED
}
