import { ActionIcon, Badge, Button, Group, Paper, Text, Textarea } from '@mantine/core'
import { useState } from 'react'

import type { CommentOut, VoteResponse } from '../api/types'
import { AttachmentGrid } from './AttachmentGrid'
import { VoteButtons } from './VoteButtons'

interface Props {
  comment: CommentOut
  isOwn: boolean
  onEdit: (body: string) => Promise<unknown>
  onDelete: () => void
  onVote: (value: 1 | -1) => Promise<VoteResponse>
  busy: boolean
}

export function CommentItem({
  comment,
  isOwn,
  onEdit,
  onDelete,
  onVote,
  busy,
}: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(comment.body)

  const save = async () => {
    if (!draft.trim()) return
    await onEdit(draft.trim())
    setEditing(false)
  }

  return (
    <Paper
      p="sm"
      style={{ borderLeft: '2px solid var(--mantine-color-ink-2)', borderRadius: 0 }}
    >
      <Group justify="space-between" gap="xs">
        <Group gap="xs">
          <Text size="sm" fw={600}>
            {comment.author_email ?? 'Anonymous (author)'}
          </Text>
          {/* Others already read "Anonymous (author)" above; the badge is what
              tells the author their own reply is anonymous. */}
          {comment.is_anonymous && comment.author_email && (
            <Badge size="xs" variant="light" color="gray">
              Anonymous (author)
            </Badge>
          )}
          <Text size="xs" c="dimmed">
            {new Date(comment.created_at).toLocaleString()}
            {comment.edited_at && ' (edited)'}
          </Text>
        </Group>
        {isOwn && !editing && (
          <Group gap={4}>
            <ActionIcon
              variant="subtle"
              size="sm"
              aria-label="Edit comment"
              onClick={() => {
                setDraft(comment.body)
                setEditing(true)
              }}
            >
              ✎
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="red"
              size="sm"
              aria-label="Delete comment"
              loading={busy}
              onClick={onDelete}
            >
              🗑
            </ActionIcon>
          </Group>
        )}
      </Group>
      {editing ? (
        <>
          <Textarea
            autosize
            minRows={2}
            mt="xs"
            value={draft}
            onChange={(e) => setDraft(e.currentTarget.value)}
          />
          <Group justify="flex-end" gap="xs" mt="xs">
            <Button variant="default" size="xs" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button size="xs" loading={busy} onClick={save}>
              Save
            </Button>
          </Group>
        </>
      ) : (
        <>
          <Text size="sm" mt="xs" style={{ whiteSpace: 'pre-wrap' }}>
            {comment.body}
          </Text>
          <AttachmentGrid attachments={comment.attachments} />
          <Group mt="xs">
            <VoteButtons
              likeCount={comment.like_count}
              dislikeCount={comment.dislike_count}
              myVote={comment.my_vote}
              onVote={onVote}
              size="compact-xs"
            />
          </Group>
        </>
      )}
    </Paper>
  )
}
