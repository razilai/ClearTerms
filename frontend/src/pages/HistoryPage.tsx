import {
  Alert,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Paper,
  Progress,
  Stack,
  Text,
} from '@mantine/core'
import {
  keepPreviousData,
  useMutationState,
  useQuery,
} from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { isNotReady } from '../api/client'
import { getHistory } from '../api/history'
import type { AnalyzeRequest } from '../api/types'
import { BackendNotReady } from '../components/BackendNotReady'
import { PageHeader } from '../components/PageHeader'
import { Pager } from '../components/Pager'
import { VerdictStamp } from '../components/VerdictStamp'
import { useKeysetPages } from '../lib/useKeysetPages'

const PAGE_SIZE = 15

export function HistoryPage() {
  const pages = useKeysetPages()
  const { data, isPending, error, isFetching } = useQuery({
    queryKey: ['history', pages.cursor],
    queryFn: () => getHistory(PAGE_SIZE, pages.cursor),
    // Hold the current page on screen while the next loads, so the list
    // doesn't collapse to a spinner on every click.
    placeholderData: keepPreviousData,
  })
  const entries = data?.items ?? []
  // Analyses fired from AnalyzePage but still in flight. The mutation cache is
  // global to the QueryClient, so these survive navigating here from /analyze;
  // each resolves via invalidateQueries(['history']), which drops it from
  // 'pending' and swaps the placeholder below for the real row.
  const pending = useMutationState({
    filters: { mutationKey: ['analyze'], status: 'pending' },
    select: (m) => m.state.variables as AnalyzeRequest,
  })

  if (isPending) {
    return (
      <Center mt="xl">
        <Loader />
      </Center>
    )
  }

  if (error) {
    return (
      <Container size="md">
        {isNotReady(error) ? (
          <BackendNotReady feature="History" />
        ) : (
          <Alert color="red" mt="md">
            Failed to load history: {error.message}
          </Alert>
        )}
      </Container>
    )
  }

  return (
    <Container size="md">
      <PageHeader
        eyebrow="§2 · History"
        title="History"
        description="Every terms-of-service document you've had reviewed."
      />
      {entries.length === 0 && pending.length === 0 ? (
        <Stack align="center" mt="xl" gap="sm">
          <Text c="ink.6">No documents reviewed yet.</Text>
          <Button component={Link} to="/analyze" variant="light">
            Run your first analysis
          </Button>
        </Stack>
      ) : (
        <Stack gap="xs">
          {pending.map((vars, i) => (
            <Paper key={`pending-${i}`} withBorder p="md">
              <Group wrap="nowrap" justify="space-between">
                <Group wrap="nowrap" gap="md" style={{ minWidth: 0 }}>
                  <Text size="xs" c="ink.6" ff="monospace">
                    Analyzing…
                  </Text>
                  <Text size="sm" fw={500} truncate>
                    {vars?.url ?? 'Pasted text'}
                  </Text>
                </Group>
                <Progress value={100} animated w={120} color="redline" />
              </Group>
            </Paper>
          ))}
          {entries.map((entry) => (
            <Paper
              key={entry.document_id}
              withBorder
              p="md"
              component={Link}
              to={`/analyses/${entry.document_id}`}
              style={{ textDecoration: 'none', color: 'inherit' }}
            >
              <Group wrap="nowrap" justify="space-between">
                <Group wrap="nowrap" gap="md" style={{ minWidth: 0 }}>
                  <Text size="xs" c="ink.6" ff="monospace">
                    No. {String(entry.document_id).padStart(6, '0')}
                  </Text>
                  <Text size="sm" fw={500} truncate>
                    {entry.url ?? 'Pasted text'}
                  </Text>
                </Group>
                <Group wrap="nowrap" gap="md">
                  <VerdictStamp verdict={entry.verdict} size="sm" />
                  <Text size="xs" c="ink.6" visibleFrom="xs">
                    {new Date(entry.created_at).toLocaleString()}
                  </Text>
                </Group>
              </Group>
            </Paper>
          ))}
        </Stack>
      )}
      <Pager
        pages={pages}
        nextCursor={data?.next_cursor ?? null}
        loading={isFetching}
      />
    </Container>
  )
}
