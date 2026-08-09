import { request } from './client'
import type { HistoryEntryOut, Page } from './types'

// One keyset page of history, newest first. Pass the previous page's
// next_cursor to fetch the next; omit it for the first page.
export function getHistory(cursor?: string | null): Promise<Page<HistoryEntryOut>> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  return request<Page<HistoryEntryOut>>(`/history${query}`)
}
