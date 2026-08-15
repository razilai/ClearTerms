import { request } from './client'
import type { HistoryEntryOut, Page } from './types'

// One keyset page of history, newest first. Pass the previous page's
// next_cursor to fetch the next; omit it for the first page.
export function getHistory(
  limit: number,
  cursor?: string | null,
): Promise<Page<HistoryEntryOut>> {
  const query = cursor
    ? `?limit=${limit}&cursor=${encodeURIComponent(cursor)}`
    : `?limit=${limit}`
  return request<Page<HistoryEntryOut>>(`/history${query}`)
}
