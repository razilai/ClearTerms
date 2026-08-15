import { Container, Grid, Paper, Stack, Text } from '@mantine/core'

import { PageHeader } from '../components/PageHeader'

// Layout only: direct messages are not built yet. The two panes are here so the
// section has its shape before the data does — conversations left, thread right.
export function MessagesPage() {
  return (
    <Container size="md">
      <PageHeader
        eyebrow="§4 · Messages"
        title="Messages"
        description="Direct messages between members. Not open yet."
      />
      <Grid>
        <Grid.Col span={{ base: 12, sm: 4 }}>
          <Paper withBorder p="md" h="100%">
            <Text size="xs" c="dimmed" tt="uppercase" mb="xs">
              Conversations
            </Text>
            <Text size="sm" c="dimmed">
              No conversations yet.
            </Text>
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 8 }}>
          <Paper withBorder p="md" h="100%" mih={280}>
            <Stack justify="center" align="center" h="100%" gap={4}>
              <Text fw={600}>Direct messages are coming</Text>
              <Text size="sm" c="dimmed" ta="center">
                Pick a conversation to read it here.
              </Text>
            </Stack>
          </Paper>
        </Grid.Col>
      </Grid>
    </Container>
  )
}
