import {
  Alert,
  Button,
  Card,
  Center,
  Container,
  Group,
  Loader,
  Stack,
  Text,
} from '@mantine/core'
import { useInfiniteQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { listPosts } from '../api/forum'
import { CategoryChip } from '../components/CategoryChip'
import { PageHeader } from '../components/PageHeader'

export function PostListPage() {
  const {
    data,
    isPending,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['posts'],
    queryFn: ({ pageParam }) => listPosts(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  })
  const posts = data?.pages.flatMap((page) => page.items) ?? []

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
              <Group justify="space-between" wrap="nowrap">
                <Text fw={600} lineClamp={1}>
                  {post.title}
                </Text>
                {post.category && <CategoryChip category={post.category} />}
              </Group>
              <Text size="sm" c="dimmed" lineClamp={2} mt={4}>
                {post.body}
              </Text>
              <Group gap="xs" mt="sm">
                <Text size="xs" c="dimmed">
                  {post.author_email}
                </Text>
                <Text size="xs" c="dimmed">
                  · {new Date(post.created_at).toLocaleString()}
                </Text>
                <Text size="xs" c="dimmed">
                  · ♥ {post.like_count}
                </Text>
              </Group>
            </Card>
          ))}
          {hasNextPage && (
            <Center mt="sm">
              <Button
                variant="subtle"
                onClick={() => fetchNextPage()}
                loading={isFetchingNextPage}
              >
                Load more
              </Button>
            </Center>
          )}
        </Stack>
      )}
    </Container>
  )
}
