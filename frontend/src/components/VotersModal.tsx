import { Button, Group, Loader, Modal, Stack, Text } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { listCommentVoters, listPostVoters } from '../api/forum'
import type { VoterOut } from '../api/types'

const PAGE_SIZE = 50

interface Props {
  kind: 'post' | 'comment'
  targetId: number
  opened: boolean
  onClose: () => void
}

/** Who liked and disliked one post or comment.
 *
 * Only ever mounted for the author of the thing being voted on — the endpoint
 * 403s anyone else, so the caller gates the affordance and the server gates
 * the data.
 */
export function VotersModal({ kind, targetId, opened, onClose }: Props) {
  const [cursor, setCursor] = useState<string | null>(null)
  const [loaded, setLoaded] = useState<VoterOut[]>([])

  const { data, isLoading } = useQuery({
    queryKey: ['voters', kind, targetId, cursor],
    queryFn: () =>
      kind === 'post'
        ? listPostVoters(targetId, PAGE_SIZE, cursor)
        : listCommentVoters(targetId, PAGE_SIZE, cursor),
    // Nothing is fetched until the modal is actually opened: every post and
    // comment you wrote would otherwise fire a request on render.
    enabled: opened,
  })

  // Pages accumulate rather than replace — this is a "load more" list, not a
  // pager, since a voter list is read straight through.
  const voters =
    cursor === null ? (data?.items ?? []) : [...loaded, ...(data?.items ?? [])]
  const likes = voters.filter((v) => v.value === 1)
  const dislikes = voters.filter((v) => v.value === -1)

  const close = () => {
    setCursor(null)
    setLoaded([])
    onClose()
  }

  return (
    <Modal opened={opened} onClose={close} title="Who voted" size="sm">
      {/* The loader only stands in for an empty list: a "load more" fetch
          changes the query key, so showing it on every page would blank out
          the names already on screen. */}
      {isLoading && voters.length === 0 ? (
        <Group justify="center" py="md">
          <Loader size="sm" />
        </Group>
      ) : voters.length === 0 ? (
        <Text c="dimmed" size="sm">
          No votes yet.
        </Text>
      ) : (
        <Stack gap="md">
          <Section title={`♥ Liked (${likes.length})`} voters={likes} />
          <Section title={`✕ Disliked (${dislikes.length})`} voters={dislikes} />
          {data?.next_cursor && (
            <Button
              variant="subtle"
              size="xs"
              onClick={() => {
                setLoaded(voters)
                setCursor(data.next_cursor)
              }}
            >
              Load more
            </Button>
          )}
        </Stack>
      )}
    </Modal>
  )
}

function Section({ title, voters }: { title: string; voters: VoterOut[] }) {
  return (
    <div>
      <Text fw={600} size="sm" mb={4}>
        {title}
      </Text>
      {voters.length === 0 ? (
        <Text c="dimmed" size="xs">
          Nobody yet.
        </Text>
      ) : (
        <Stack gap={2}>
          {voters.map((v) => (
            <Text key={v.email} size="sm">
              {v.email}
            </Text>
          ))}
        </Stack>
      )}
    </div>
  )
}
