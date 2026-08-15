import {
  Alert,
  Badge,
  Card,
  Center,
  Container,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { getMyVoteTotals, listMyPosts } from '../api/forum'
import { useAuth } from '../auth/useAuth'
import { PageHeader } from '../components/PageHeader'
import { Pager } from '../components/Pager'
import { PreferencesPanel } from '../components/PreferencesPanel'
import { useKeysetPages } from '../lib/useKeysetPages'

// Deliberately smaller than the Forum and History pages: this list is one
// section among several, not the whole screen.
const PAGE_SIZE = 5

function Stat({ label, value }: { label: string; value: number | undefined }) {
  return (
    <Paper withBorder p="md">
      <Text size="xs" c="dimmed" tt="uppercase">
        {label}
      </Text>
      <Text fz={28} fw={600} lh={1.2} mt={4}>
        {value ?? '—'}
      </Text>
    </Paper>
  )
}

export function PersonalAreaPage() {
  const { email } = useAuth()
  const pages = useKeysetPages()

  const totals = useQuery({
    queryKey: ['my-vote-totals'],
    queryFn: getMyVoteTotals,
  })
  const posts = useQuery({
    queryKey: ['my-posts', pages.cursor],
    queryFn: () => listMyPosts(PAGE_SIZE, pages.cursor),
    // Keep the current page on screen while the next one loads, so the list
    // doesn't collapse to a spinner on every click.
    placeholderData: keepPreviousData,
  })

  return (
    <Container size="md">
      <PageHeader
        eyebrow="§5 · Personal area"
        title="Personal area"
        description={email ?? undefined}
      />

      <SimpleGrid cols={{ base: 1, xs: 3 }} mb="xl">
        <Stat label="Posts" value={totals.data?.post_count} />
        <Stat label="Likes received" value={totals.data?.like_count} />
        <Stat label="Dislikes received" value={totals.data?.dislike_count} />
      </SimpleGrid>
      {totals.error && (
        <Alert color="red" mb="xl">
          Failed to load your totals: {totals.error.message}
        </Alert>
      )}

      <Title order={2} size="h4" mb="sm">
        My posts
      </Title>
      {posts.isPending ? (
        <Center my="xl">
          <Loader />
        </Center>
      ) : posts.error ? (
        <Alert color="red">Failed to load your posts: {posts.error.message}</Alert>
      ) : posts.data.items.length === 0 ? (
        <Text c="dimmed" ta="center" my="xl">
          You haven't posted yet.{' '}
          <Link to="/forum/new">Start a discussion.</Link>
        </Text>
      ) : (
        <Stack gap="sm">
          {posts.data.items.map((post) => (
            <Card
              key={post.id}
              withBorder
              padding="md"
              component={Link}
              to={`/forum/${post.id}`}
              style={{ textDecoration: 'none', color: 'inherit' }}
            >
              <Group justify="space-between" wrap="nowrap">
                <Text fw={600} lineClamp={1}>
                  {post.title}
                </Text>
                {post.is_anonymous && (
                  <Badge size="xs" variant="light" color="gray">
                    Anonymous
                  </Badge>
                )}
              </Group>
              <Text size="sm" c="dimmed" lineClamp={2} mt={4}>
                {post.body}
              </Text>
              <Text size="xs" c="dimmed" mt="sm">
                {new Date(post.created_at).toLocaleString()} · ♥ {post.like_count} ·
                ✕ {post.dislike_count}
              </Text>
            </Card>
          ))}
        </Stack>
      )}
      <Pager
        pages={pages}
        nextCursor={posts.data?.next_cursor ?? null}
        loading={posts.isFetching}
      />

      <Title order={2} size="h4" mt="xl" mb="sm">
        Preferences
      </Title>
      <Text size="sm" c="dimmed" mb="md">
        Which clause types your reports cover.
      </Text>
      <PreferencesPanel />
    </Container>
  )
}
