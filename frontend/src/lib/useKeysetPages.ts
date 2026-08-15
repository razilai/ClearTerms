import { useState } from 'react'

export interface KeysetPages {
  // Cursor for the page currently on screen; null is the first page.
  cursor: string | null
  pageIndex: number
  hasPrev: boolean
  goPrev: () => void
  // Takes the current page's next_cursor rather than closing over it: the
  // caller can only learn it from a query that this hook's `cursor` keys, so
  // the hook cannot receive it up front without a cycle.
  goNext: (nextCursor: string | null) => void
}

// Discrete page navigation over the backend's keyset cursors.
//
// The backend pages forward-only: a page hands back the cursor that opens the
// *next* one and nothing that opens the previous. So going back means replaying
// a cursor already visited — this keeps the stack of them, where cursors[i]
// opens page i and cursors[0] is null, the first page.
export function useKeysetPages(): KeysetPages {
  const [cursors, setCursors] = useState<(string | null)[]>([null])
  const [pageIndex, setPageIndex] = useState(0)

  const goNext = (nextCursor: string | null) => {
    if (!nextCursor) return
    // Truncate past pageIndex before pushing: paging back and then forward
    // again re-derives the tail, and a stale entry there would open the wrong
    // page if the list shifted in between.
    setCursors((prev) => [...prev.slice(0, pageIndex + 1), nextCursor])
    setPageIndex((i) => i + 1)
  }

  return {
    cursor: cursors[pageIndex],
    pageIndex,
    hasPrev: pageIndex > 0,
    goPrev: () => setPageIndex((i) => Math.max(0, i - 1)),
    goNext,
  }
}
