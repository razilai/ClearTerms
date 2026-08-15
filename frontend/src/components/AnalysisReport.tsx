import { Anchor, Box, Group, Stack, Text } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { getPreferences } from '../api/preferences'
import type { AnalysisDetail } from '../api/types'
import { CATEGORY_ORDER, enabledCategories } from '../lib/categories'
import { ScoreMark } from './ScoreMark'
import { VerdictStamp } from './VerdictStamp'

interface Props {
  detail: AnalysisDetail
  verdict?: string
}

// Known categories in canonical order first, anything the backend added later
// appended in the order it sent them.
function orderScores(detail: AnalysisDetail) {
  const byCategory = new Map(detail.scores.map((s) => [s.category, s]))
  const known = CATEGORY_ORDER.flatMap((c) => {
    const s = byCategory.get(c)
    return s ? [s] : []
  })
  const extra = detail.scores.filter(
    (s) => !(CATEGORY_ORDER as readonly string[]).includes(s.category),
  )
  return [...known, ...extra]
}

// The backend returns every category it scored — filtering is a read-time,
// per-user concern, so it happens here. Sharing the ['preferences'] query key
// with PreferencesPanel means a toggle there re-renders open reports without a
// refetch.
export function AnalysisReport({ detail, verdict }: Props) {
  const preferences = useQuery({
    queryKey: ['preferences'],
    queryFn: getPreferences,
    // A report is still worth reading if preferences fail to load; the
    // undefined case in enabledCategories() hides nothing.
    retry: false,
  })
  const isEnabled = enabledCategories(preferences.data?.items)
  const ordered = orderScores(detail)
  const shown = ordered.filter((entry) => isEnabled(entry.category))
  const hiddenCount = ordered.length - shown.length

  return (
    <Box>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={2}>
          <Text fw={500} style={{ wordBreak: 'break-all' }}>
            {detail.url ?? 'Pasted text'}
          </Text>
          <Text size="xs" c="ink.6" ff="monospace">
            No. {String(detail.id).padStart(6, '0')} ·{' '}
            {new Date(detail.created_at).toLocaleString()} · model{' '}
            {detail.model_version}
          </Text>
        </Stack>
        {verdict && <VerdictStamp verdict={verdict} size="sm" />}
      </Group>
      <Box mt="md">
        {shown.map((entry, i) => (
          <ScoreMark key={entry.category} entry={entry} index={i} />
        ))}
      </Box>
      {hiddenCount > 0 && (
        <Text size="xs" c="ink.6" mt="sm">
          {hiddenCount} clause {hiddenCount === 1 ? 'type is' : 'types are'}{' '}
          hidden by your{' '}
          <Anchor component={Link} to="/me" size="xs" inherit>
            preferences
          </Anchor>
          .
        </Text>
      )}
    </Box>
  )
}
