import {
  Alert,
  Badge,
  Button,
  Card,
  Center,
  Container,
  Group,
  Loader,
  Stack,
  Text,
} from '@mantine/core'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { listPosts } from '../api/forum'
import { PageHeader } from '../components/PageHeader'
import { Pager } from '../components/Pager'
import { useKeysetPages } from '../lib/useKeysetPages'

const PAGE_SIZE = 15

export function PostListPage() {
  const pages = useKeysetPages()
  const { data, isPending, error, isFetching } = useQuery({
    queryKey: ['posts', pages.cursor],
    queryFn: () => listPosts(PAGE_SIZE, pages.cursor),
    // Hold the current page on screen while the next loads, so the list
    // doesn't collapse to a spinner on every click.
    placeholderData: keepPreviousData,
  })
  const posts = data?.items ?? []

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
        <Alert color="red" mt="md">
          Failed to load posts: {error.message}
        </Alert>
      </Container>
    )
  }

  return (
    <Container size="md">
      <PageHeader
        eyebrow="§3 · Forum"
        title="Forum"
        description="Compare clauses and share what you've turned up in the fine print."
        action={
          <Button component={Link} to="/forum/new">
            New post
          </Button>
        }
      />
      {posts.length === 0 ? (
        <Text c="dimmed" ta="center" mt="xl">
          No posts yet. Start the first discussion!
        </Text>
      ) : (
        <Stack gap="sm">
          {posts.map((post) => (
            <Card
              key={post.id}
              withBorder
              padding="md"
              component={Link}
              to={`/forum/${post.id}`}
              style={{ textDecoration: 'none', color: 'inherit' }}
            >
              <Text fw={600} lineClamp={1}>
                {post.title}
              </Text>
              <Text size="sm" c="dimmed" lineClamp={2} mt={4}>
                {post.body}
              </Text>
              <Group gap="xs" mt="sm">
                <Text size="xs" c="dimmed">
                  {post.author_email ?? 'Anonymous'}
                </Text>
                {/* The byline already reads "Anonymous" for everyone else; the
                    badge is what tells the author their own post is anonymous. */}
                {post.is_anonymous && post.author_email && (
                  <Badge size="xs" variant="light" color="gray">
                    Anonymous
                  </Badge>
                )}
                <Text size="xs" c="dimmed">
                  · {new Date(post.created_at).toLocaleString()}
                </Text>
                <Text size="xs" c="dimmed">
                  · ♥ {post.like_count} · ✕ {post.dislike_count}
                </Text>
                {post.attachments.length > 0 && (
                  <Text size="xs" c="dimmed">
                    · 📎 {post.attachments.length}
                  </Text>
                )}
              </Group>
            </Card>
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
