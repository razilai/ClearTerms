import {
  Alert,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  Textarea,
  Title,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  addComment,
  deleteComment,
  deletePost,
  editComment,
  getPost,
  toggleLike,
} from '../api/forum'
import type { LikeResponse, PostDetail } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { CategoryChip } from '../components/CategoryChip'
import { CommentItem } from '../components/CommentItem'

const showError = (err: Error) =>
  notifications.show({ color: 'red', message: err.message })

export function PostDetailPage() {
  const { postId: postIdParam } = useParams()
  const postId = Number(postIdParam)
  const { email } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [commentDraft, setCommentDraft] = useState('')
  // Backend reports liked-state only in the toggle response, so it's unknown
  // until the first click.
  const [liked, setLiked] = useState<boolean | null>(null)
  const [confirmOpen, { open: openConfirm, close: closeConfirm }] =
    useDisclosure(false)

  const postKey = ['post', postId]
  const {
    data: post,
    isPending,
    error,
  } = useQuery({ queryKey: postKey, queryFn: () => getPost(postId) })

  const invalidatePost = () => {
    queryClient.invalidateQueries({ queryKey: postKey })
  }

  const likeMutation = useMutation({
    mutationFn: () => toggleLike(postId),
    onSuccess: ({ like_count, liked: nowLiked }: LikeResponse) => {
      setLiked(nowLiked)
      queryClient.setQueryData<PostDetail>(postKey, (old) =>
        old ? { ...old, like_count } : old,
      )
      queryClient.invalidateQueries({ queryKey: ['posts'] })
    },
    onError: showError,
  })

  const addCommentMutation = useMutation({
    mutationFn: (body: string) => addComment(postId, body),
    onSuccess: () => {
      setCommentDraft('')
      invalidatePost()
    },
    onError: showError,
  })

  const editCommentMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: string }) =>
      editComment(id, body),
    onSuccess: invalidatePost,
    onError: showError,
  })

  const deleteCommentMutation = useMutation({
    mutationFn: (id: number) => deleteComment(id),
    onSuccess: invalidatePost,
    onError: showError,
  })

  const deletePostMutation = useMutation({
    mutationFn: () => deletePost(postId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['posts'] })
      queryClient.removeQueries({ queryKey: postKey })
      navigate('/forum')
    },
    onError: (err) => {
      closeConfirm()
      showError(err)
    },
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
        <Alert color="red" mt="md">
          Failed to load post: {error.message}
        </Alert>
        <Button variant="default" mt="md" onClick={() => navigate('/forum')}>
          Back to posts
        </Button>
      </Container>
    )
  }

  const isOwnPost = post.author_email === email

  return (
    <Container size="md">
      <Button variant="subtle" size="xs" mb="sm" onClick={() => navigate('/forum')}>
        ← All posts
      </Button>
      <Paper withBorder p="lg">
        <Group justify="space-between" wrap="nowrap">
          <Title order={2}>{post.title}</Title>
          {post.category && <CategoryChip category={post.category} />}
        </Group>
        <Text
          size="sm"
          c="dimmed"
          mt={4}
          pb="sm"
          style={{ borderBottom: '1px solid var(--mantine-color-ink-1)' }}
        >
          {post.author_email} · {new Date(post.created_at).toLocaleString()}
        </Text>
        <Text
          mt="md"
          style={{
            whiteSpace: 'pre-wrap',
            borderLeft: '2px solid var(--mantine-color-redline-6)',
            paddingLeft: 20,
            fontFamily: 'Spectral, Georgia, serif',
            fontSize: '1.05rem',
            lineHeight: 1.65,
          }}
        >
          {post.body}
        </Text>
        <Group mt="lg" justify="space-between">
          <Button
            variant={liked ? 'filled' : 'light'}
            size="xs"
            loading={likeMutation.isPending}
            onClick={() => likeMutation.mutate()}
          >
            ♥ {post.like_count}
          </Button>
          {isOwnPost && (
            <Button color="red" variant="light" size="xs" onClick={openConfirm}>
              Delete post
            </Button>
          )}
        </Group>
      </Paper>

      <Title order={4} mt="xl" mb="sm">
        Comments ({post.comments.length})
      </Title>
      <Stack gap="sm">
        {post.comments.map((comment) => (
          <CommentItem
            key={comment.id}
            comment={comment}
            isOwn={comment.author_email === email}
            busy={
              editCommentMutation.isPending || deleteCommentMutation.isPending
            }
            onEdit={(body) =>
              editCommentMutation.mutateAsync({ id: comment.id, body })
            }
            onDelete={() => deleteCommentMutation.mutate(comment.id)}
          />
        ))}
      </Stack>

      <Paper withBorder p="md" mt="md">
        <Textarea
          placeholder="Write a comment…"
          autosize
          minRows={2}
          value={commentDraft}
          onChange={(e) => setCommentDraft(e.currentTarget.value)}
        />
        <Group justify="flex-end" mt="sm">
          <Button
            size="xs"
            disabled={!commentDraft.trim()}
            loading={addCommentMutation.isPending}
            onClick={() => addCommentMutation.mutate(commentDraft.trim())}
          >
            Comment
          </Button>
        </Group>
      </Paper>

      <Modal opened={confirmOpen} onClose={closeConfirm} title="Delete post?">
        <Text size="sm">
          This permanently deletes the post and its comments.
        </Text>
        <Group justify="flex-end" mt="lg">
          <Button variant="default" onClick={closeConfirm}>
            Cancel
          </Button>
          <Button
            color="red"
            loading={deletePostMutation.isPending}
            onClick={() => deletePostMutation.mutate()}
          >
            Delete
          </Button>
        </Group>
      </Modal>
    </Container>
  )
}
