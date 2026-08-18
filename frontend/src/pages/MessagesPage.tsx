import {
  Alert,
  Badge,
  Button,
  Center,
  Container,
  Grid,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  TextInput,
  Textarea,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  conversationsKey,
  getConversation,
  listConversations,
  listMessages,
  markRead,
  sendMessage,
  startConversation,
  unreadKey,
} from '../api/messages'
import { ApiError } from '../api/client'
import type { MessageOut } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { AttachmentGrid } from '../components/AttachmentGrid'
import { CharCount } from '../components/CharCount'
import { MediaDropzone } from '../components/MediaDropzone'
import { PageHeader } from '../components/PageHeader'
import { Pager } from '../components/Pager'
import { MAX_MESSAGE_BODY_CHARS } from '../lib/limits'
import { useKeysetPages } from '../lib/useKeysetPages'

const PAGE_SIZE = 15
const OLDER_PAGE_SIZE = 30

const showError = (err: Error) =>
  notifications.show({ color: 'red', message: err.message })

function ConversationList({
  selectedId,
  onSelect,
}: {
  selectedId: number | null
  onSelect: (id: number) => void
}) {
  const pages = useKeysetPages()
  const { data, isPending, error, isFetching } = useQuery({
    queryKey: [...conversationsKey, pages.cursor],
    queryFn: () => listConversations(PAGE_SIZE, pages.cursor),
    placeholderData: keepPreviousData,
  })

  if (isPending) {
    return (
      <Center py="lg">
        <Loader size="sm" />
      </Center>
    )
  }
  if (error) {
    return (
      <Alert color="red">Failed to load conversations: {error.message}</Alert>
    )
  }

  const conversations = data?.items ?? []
  if (conversations.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No conversations yet.
      </Text>
    )
  }

  return (
    <>
      <Stack gap="xs">
        {conversations.map((conversation) => (
          <Paper
            key={conversation.id}
            withBorder
            p="sm"
            onClick={() => onSelect(conversation.id)}
            // Selection reads as a redline margin mark, not a fill — the theme
            // pins Paper's background, and a tint would fight the paper stock.
            style={{
              cursor: 'pointer',
              borderLeft: `3px solid ${
                conversation.id === selectedId
                  ? 'var(--mantine-color-redline-6)'
                  : 'transparent'
              }`,
            }}
          >
            <Group justify="space-between" wrap="nowrap" gap="xs">
              <Text size="sm" fw={600} lineClamp={1}>
                {conversation.other_email}
              </Text>
              {conversation.unread_count > 0 && (
                <Badge size="sm" circle>
                  {conversation.unread_count}
                </Badge>
              )}
            </Group>
            <Text size="xs" c="dimmed" lineClamp={1} mt={2}>
              {conversation.last_message?.body ?? 'No messages yet'}
            </Text>
            <Text size="xs" c="dimmed" mt={2}>
              {new Date(conversation.last_message_at).toLocaleString()}
            </Text>
          </Paper>
        ))}
      </Stack>
      <Pager
        pages={pages}
        nextCursor={data?.next_cursor ?? null}
        loading={isFetching}
      />
    </>
  )
}

function Thread({ conversationId }: { conversationId: number }) {
  const { email } = useAuth()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState('')
  // State rather than a ref (the forum uses a ref): here the Send button has to
  // re-enable when attachments arrive, because a picture with no caption is a
  // valid message. MediaDropzone only fires onChange from event handlers, so
  // setting state from it cannot loop.
  const [attachmentIds, setAttachmentIds] = useState<number[]>([])
  const [dropzoneKey, setDropzoneKey] = useState(0)
  // Pages fetched by "Load older", oldest-first once reversed for display.
  const [older, setOlder] = useState<MessageOut[]>([])
  const [olderCursor, setOlderCursor] = useState<string | null>(null)

  const threadKey = ['conversation', conversationId]
  const { data, isPending, error } = useQuery({
    queryKey: threadKey,
    queryFn: () => getConversation(conversationId),
  })

  // A fresh thread resets the accumulated older pages, or they would bleed
  // from the previously open conversation into this one.
  useEffect(() => {
    setOlder([])
    setOlderCursor(null)
    setDraft('')
    // Switching threads must drop staged attachments too, or they would be
    // claimed by the next message in a different conversation.
    setAttachmentIds([])
    setDropzoneKey((k) => k + 1)
  }, [conversationId])

  useEffect(() => {
    if (data) setOlderCursor(data.messages_next_cursor)
  }, [data])

  // Opening a thread clears its unread messages; the inbox badge and the nav
  // badge both key off queries this invalidates.
  const read = useMutation({
    mutationFn: () => markRead(conversationId),
    onSuccess: (result) => {
      if (result.marked_count === 0) return
      queryClient.invalidateQueries({ queryKey: conversationsKey })
      queryClient.invalidateQueries({ queryKey: unreadKey })
    },
  })
  const { mutate: markThreadRead } = read
  useEffect(() => {
    if (data) markThreadRead()
  }, [data, markThreadRead])

  const send = useMutation({
    mutationFn: (body: string) =>
      sendMessage(conversationId, body, attachmentIds),
    onSuccess: () => {
      setDraft('')
      // Remount the dropzone so the just-claimed attachments clear: an id can
      // only be claimed once, so re-sending them would 404.
      setAttachmentIds([])
      setDropzoneKey((k) => k + 1)
      queryClient.invalidateQueries({ queryKey: threadKey })
      queryClient.invalidateQueries({ queryKey: conversationsKey })
    },
    onError: showError,
  })

  const loadOlder = useMutation({
    mutationFn: () => listMessages(conversationId, OLDER_PAGE_SIZE, olderCursor),
    onSuccess: (page) => {
      setOlder((prev) => [...prev, ...page.items])
      setOlderCursor(page.next_cursor)
    },
    onError: showError,
  })

  if (isPending) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    )
  }
  if (error) {
    return <Alert color="red">Failed to load conversation: {error.message}</Alert>
  }

  // The API returns newest-first; reverse so the thread reads top-old to
  // bottom-new the way a conversation is actually read.
  const messages = [...data.messages, ...older].reverse()
  const tooLong = draft.length > MAX_MESSAGE_BODY_CHARS
  // An attachment with no caption is a message; empty text alone is not.
  const canSend = Boolean(draft.trim()) || attachmentIds.length > 0

  return (
    <Stack h="100%" gap="sm">
      <Text fw={600}>{data.other_email}</Text>
      {olderCursor && (
        <Button
          variant="subtle"
          size="xs"
          loading={loadOlder.isPending}
          onClick={() => loadOlder.mutate()}
        >
          Load older messages
        </Button>
      )}
      <Stack gap="xs" style={{ flex: 1 }}>
        {messages.length === 0 && (
          <Text size="sm" c="dimmed">
            No messages yet — say something.
          </Text>
        )}
        {messages.map((message) => {
          const mine = message.sender_email === email
          return (
            <Paper
              key={message.id}
              p="sm"
              maw="80%"
              ml={mine ? 'auto' : undefined}
              // Hairline rule rather than a filled bubble, matching CommentItem
              // and the rest of the document surfaces. The rule sits on the edge
              // the message is aligned to, and inks redline when it is yours.
              style={{
                borderRadius: 0,
                [mine ? 'borderRight' : 'borderLeft']: `2px solid var(--mantine-color-${
                  mine ? 'redline-3' : 'ink-2'
                })`,
              }}
            >
              <Group justify="space-between" gap="sm" wrap="nowrap" align="baseline">
                <Text size="sm" fw={600}>
                  {mine ? 'You' : message.sender_email}
                </Text>
                <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                  {new Date(message.created_at).toLocaleString([], {
                    dateStyle: 'medium',
                    timeStyle: 'short',
                  })}
                </Text>
              </Group>
              {message.body && (
                <Text size="sm" mt={6} style={{ whiteSpace: 'pre-wrap' }}>
                  {message.body}
                </Text>
              )}
              <AttachmentGrid attachments={message.attachments} />
              {/* Own messages only: read_at answers "have they seen it yet?".
                  On one you received it is always set by the time you could
                  look — opening the thread is what sets it. */}
              {mine && (
                <Text
                  mt={6}
                  ta="right"
                  c={message.read_at ? 'ok.7' : 'ink.5'}
                  style={{
                    fontFamily: 'var(--mantine-font-family-monospace)',
                    fontSize: '0.65rem',
                    textTransform: 'uppercase',
                    letterSpacing: '0.06em',
                  }}
                >
                  {message.read_at
                    ? `Read ${new Date(message.read_at).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}`
                    : 'Sent'}
                </Text>
              )}
            </Paper>
          )
        })}
      </Stack>
      <div>
        <Textarea
          placeholder="Write a message"
          autosize
          minRows={2}
          value={draft}
          onChange={(event) => setDraft(event.currentTarget.value)}
        />
        <CharCount value={draft} max={MAX_MESSAGE_BODY_CHARS} />
        {/* Same pre-upload flow as the forum: files upload on drop and the
            ready ids ride along with the send. Size/type limits are enforced
            server-side by media.validate_upload. */}
        <MediaDropzone
          key={dropzoneKey}
          onChange={setAttachmentIds}
          disabled={send.isPending}
        />
        <Group justify="flex-end" mt="xs">
          <Button
            disabled={!canSend || tooLong}
            loading={send.isPending}
            onClick={() => send.mutate(draft)}
          >
            Send
          </Button>
        </Group>
      </div>
    </Stack>
  )
}

function NewConversation({ onOpened }: { onOpened: (id: number) => void }) {
  const [recipient, setRecipient] = useState('')
  const [recipientError, setRecipientError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const start = useMutation({
    mutationFn: () => startConversation(recipient.trim()),
    onSuccess: (conversation) => {
      setRecipient('')
      setRecipientError(null)
      // Idempotent server-side, so this may be an existing thread; refresh the
      // list either way in case it is genuinely new.
      queryClient.invalidateQueries({ queryKey: conversationsKey })
      onOpened(conversation.id)
    },
    onError: (err) => {
      // Starting a conversation is the only request in this component where a
      // 404 means the typed recipient has no account. Keep that actionable
      // feedback beside the field instead of exposing the API's bare "user"
      // detail in a transient notification.
      if (err instanceof ApiError && err.status === 404) {
        setRecipientError('User invalid')
        return
      }
      showError(err)
    },
  })

  return (
    <Group gap="xs" align="flex-end" wrap="nowrap">
      <TextInput
        style={{ flex: 1 }}
        size="xs"
        label="New message"
        placeholder="their@email.com"
        value={recipient}
        error={recipientError}
        onChange={(event) => {
          setRecipient(event.currentTarget.value)
          if (recipientError) setRecipientError(null)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && recipient.trim()) start.mutate()
        }}
      />
      <Button
        size="xs"
        disabled={!recipient.trim()}
        loading={start.isPending}
        onClick={() => start.mutate()}
      >
        Start
      </Button>
    </Group>
  )
}

export function MessagesPage() {
  const { conversationId: conversationIdParam } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const selectedId = conversationIdParam ? Number(conversationIdParam) : null

  // Opening the inbox refreshes the badge regardless of the poll's schedule,
  // so arriving here never shows a stale count.
  useEffect(() => {
    queryClient.invalidateQueries({ queryKey: unreadKey })
    queryClient.invalidateQueries({ queryKey: conversationsKey })
  }, [queryClient])

  const open = (id: number) => navigate(`/messages/${id}`)

  return (
    <Container size="md">
      <PageHeader
        eyebrow="§4 · Messages"
        title="Messages"
        description="Direct messages between members."
      />
      <Grid>
        <Grid.Col span={{ base: 12, sm: 4 }}>
          <Paper withBorder p="md" h="100%">
            <Text size="xs" c="dimmed" tt="uppercase" mb="xs">
              Conversations
            </Text>
            <NewConversation onOpened={open} />
            <Stack gap="xs" mt="sm">
              <ConversationList selectedId={selectedId} onSelect={open} />
            </Stack>
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 8 }}>
          <Paper withBorder p="md" h="100%" mih={280}>
            {selectedId === null ? (
              <Stack justify="center" align="center" h="100%" gap={4}>
                <Text fw={600}>No conversation open</Text>
                <Text size="sm" c="dimmed" ta="center">
                  Pick one on the left, or start a new one by email.
                </Text>
              </Stack>
            ) : (
              <Thread key={selectedId} conversationId={selectedId} />
            )}
          </Paper>
        </Grid.Col>
      </Grid>
    </Container>
  )
}
