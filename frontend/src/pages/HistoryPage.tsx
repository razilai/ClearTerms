import {
  Alert,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
} from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { isNotReady } from '../api/client'
import { getHistory } from '../api/history'
import { BackendNotReady } from '../components/BackendNotReady'
import { PageHeader } from '../components/PageHeader'
import { VerdictStamp } from '../components/VerdictStamp'

export function HistoryPage() {
  const { data, isPending, error } = useQuery({
    queryKey: ['history'],
    queryFn: getHistory,
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
      {data.entries.length === 0 ? (
        <Stack align="center" mt="xl" gap="sm">
          <Text c="ink.6">No documents reviewed yet.</Text>
          <Button component={Link} to="/analyze" variant="light">
            Run your first analysis
          </Button>
        </Stack>
      ) : (
        <Stack gap="xs">
          {data.entries.map((entry) => (
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
    </Container>
  )
}
