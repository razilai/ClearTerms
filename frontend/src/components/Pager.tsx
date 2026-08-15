import { Button, Group, Text } from '@mantine/core'

import type { KeysetPages } from '../lib/useKeysetPages'

interface Props {
  pages: KeysetPages
  // The current page's next_cursor; null means this is the last page.
  nextCursor: string | null
  // The list's in-flight state, so Next spins while the page it opens loads.
  loading?: boolean
}

// Page navigation for a keyset-paged list. Renders nothing when the whole list
// fits on one page — a lone disabled "Page 1" is noise.
export function Pager({ pages, nextCursor, loading }: Props) {
  if (!pages.hasPrev && !nextCursor) return null

  return (
    <Group justify="center" gap="lg" mt="md">
      <Button variant="subtle" disabled={!pages.hasPrev} onClick={pages.goPrev}>
        ← Previous
      </Button>
      <Text size="sm" c="dimmed">
        Page {pages.pageIndex + 1}
      </Text>
      <Button
        variant="subtle"
        disabled={!nextCursor}
        loading={loading}
        onClick={() => pages.goNext(nextCursor)}
      >
        Next →
      </Button>
    </Group>
  )
}
