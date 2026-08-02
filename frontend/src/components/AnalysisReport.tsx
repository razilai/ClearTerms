import { Box, Group, Stack, Text } from '@mantine/core'

import type { AnalysisDetail } from '../api/types'
import { CATEGORY_ORDER } from '../lib/categories'
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

export function AnalysisReport({ detail, verdict }: Props) {
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
        {orderScores(detail).map((entry, i) => (
          <ScoreMark key={entry.category} entry={entry} index={i} />
        ))}
      </Box>
    </Box>
  )
}
