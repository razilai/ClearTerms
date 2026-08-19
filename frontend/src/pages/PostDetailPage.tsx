import {
  Alert,
  Badge,
  Box,
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
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  addCommentWithAttachments,
  deleteComment,
  deletePost,
  editComment,
  getPost,
  listComments,
  voteComment,
  votePost,
} from '../api/forum'
import type { CommentOut } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { AttachmentGrid } from '../components/AttachmentGrid'
import { CharCount } from '../components/CharCount'
import { CommentItem } from '../components/CommentItem'
import { MediaDropzone } from '../components/MediaDropzone'
import { VoteButtons } from '../components/VoteButtons'
import { VotersModal } from '../components/VotersModal'
import { MAX_COMMENT_BODY_CHARS } from '../lib/limits'

const showError = (err: Error) =>
  notifications.show({ color: 'red', message: err.message })

export function PostDetailPage() {
  const { postId: postIdParam } = useParams()
  const postId = Number(postIdParam)
  const { email } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [commentDraft, setCommentDraft] = useState('')
  const commentAttachmentIdsRef = useRef<number[]>([])
  const [confirmOpen, { open: openConfirm, close: closeConfirm }] =
    useDisclosure(false)

  const postKey = ['post', postId]
  const {
    data: post,
    isPending,
    error,
  } = useQuery({ queryKey: postKey, queryFn: () => getPost(postId) })

  // The post detail ships the first keyset page of comments; further pages are
  // pulled on demand and appended here. Reset whenever the post (re)loads, so a
  // refetch after posting a comment starts from a fresh first page.
  const [extraComments, setExtraComments] = useState<CommentOut[]>([])
  const [commentsCursor, setCommentsCursor] = useState<string | null>(null)
  const [loadingComments, setLoadingComments] = useState(false)
  const [votersOpen, setVotersOpen] = useState(false)

  useEffect(() => {
    if (post) {
      setExtraComments([])
      setCommentsCursor(post.comments_next_cursor)
    }
  }, [post])

  const loadMoreComments = async () => {
    if (!commentsCursor) return
    setLoadingComments(true)
    try {
      const page = await listComments(postId, commentsCursor)
      setExtraComments((prev) => [...prev, ...page.items])
      setCommentsCursor(page.next_cursor)
    } catch (err) {
      showError(err as Error)
    } finally {
      setLoadingComments(false)
    }
  }

  const invalidatePost = () => {
    queryClient.invalidateQueries({ queryKey: postKey })
  }

  const addCommentMutation = useMutation({
    mutationFn: ({ body, attachmentIds }: { body: string; attachmentIds: number[] }) =>
      addCommentWithAttachments(postId, body, attachmentIds),
    onSuccess: () => {
      setCommentDraft('')
      commentAttachmentIdsRef.current = []
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

  const handleCommentAttachmentChange = useCallback((ids: number[]) => {
    commentAttachmentIdsRef.current = ids
  }, [])

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
  const comments = [...post.comments, ...extraComments]

  return (
    <Container size="md">
      <Button variant="subtle" size="xs" mb="sm" onClick={() => navigate('/forum')}>
        ← All posts
      </Button>
      <Paper withBorder p="lg">
        <Title order={2}>{post.title}</Title>
        <Text
          size="sm"
          c="dimmed"
          mt={4}
          pb="sm"
          style={{ borderBottom: '1px solid var(--mantine-color-ink-1)' }}
        >
          {post.author_email ?? 'Anonymous'}
          {/* Other users already see "Anonymous" above; this badge is how the
              author knows this particular post of theirs is anonymous. */}
          {post.is_anonymous && post.author_email && (
            <Badge size="xs" variant="light" color="gray" ml="xs">
              Anonymous
            </Badge>
          )}{' '}
          · {new Date(post.created_at).toLocaleString()}
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
        <AttachmentGrid attachments={post.attachments} />
        <Group mt="lg" justify="space-between">
          <VoteButtons
            likeCount={post.like_count}
            dislikeCount={post.dislike_count}
            myVote={post.my_vote}
            onVote={async (value) => {
              const result = await votePost(postId, value)
              // The list page shows the same counts — let it refetch.
              queryClient.invalidateQueries({ queryKey: ['posts'] })
              return result
            }}
            onShowVoters={isOwnPost ? () => setVotersOpen(true) : undefined}
          />
          <VotersModal
            kind="post"
            targetId={postId}
            opened={votersOpen}
            onClose={() => setVotersOpen(false)}
          />
          {isOwnPost && (
            <Button color="red" variant="light" size="xs" onClick={openConfirm}>
              Delete post
            </Button>
          )}
        </Group>
      </Paper>

      <Title order={4} mt="xl" mb="sm">
        Comments ({comments.length}
        {commentsCursor ? '+' : ''})
      </Title>
      <Stack gap="sm">
        {comments.map((comment) => (
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
            onVote={(value) => voteComment(comment.id, value)}
          />
        ))}
        {commentsCursor && (
          <Center>
            <Button
              variant="subtle"
              size="xs"
              loading={loadingComments}
              onClick={loadMoreComments}
            >
              Load more comments
            </Button>
          </Center>
        )}
      </Stack>

      <Paper withBorder p="md" mt="md">
        <Textarea
          placeholder="Write a comment…"
          autosize
          minRows={2}
          maxLength={MAX_COMMENT_BODY_CHARS}
          value={commentDraft}
          onChange={(e) => setCommentDraft(e.currentTarget.value)}
        />
        <CharCount value={commentDraft} max={MAX_COMMENT_BODY_CHARS} />
        <Box mt="sm">
          <MediaDropzone
            onChange={handleCommentAttachmentChange}
            disabled={addCommentMutation.isPending}
          />
        </Box>
        <Group justify="flex-end" mt="sm">
          <Button
            size="xs"
            disabled={!commentDraft.trim()}
            loading={addCommentMutation.isPending}
            onClick={() =>
              addCommentMutation.mutate({
                body: commentDraft.trim(),
                attachmentIds: commentAttachmentIdsRef.current,
              })
            }
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
