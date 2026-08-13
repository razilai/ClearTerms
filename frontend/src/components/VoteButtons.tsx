import { Button, Group } from '@mantine/core'
import { useEffect, useState } from 'react'

import type { VoteResponse } from '../api/types'

interface Props {
  likeCount: number
  dislikeCount: number
  myVote: number
  onVote: (value: 1 | -1) => Promise<VoteResponse>
  size?: 'compact-xs' | 'xs'
}

/**
 * Like/dislike pair for a post or a comment.
 *
 * It holds its own counts, seeded from props and replaced by the server's
 * response. That keeps callers out of the business of patching state: comments
 * live in two containers on the post page (the query cache and the appended
 * `extraComments` array), and a component that owns its own numbers does not
 * care which one it came from. Props win again whenever the parent refetches.
 */
export function VoteButtons({
  likeCount,
  dislikeCount,
  myVote,
  onVote,
  size = 'xs',
}: Props) {
  const [state, setState] = useState({ likeCount, dislikeCount, myVote })
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setState({ likeCount, dislikeCount, myVote })
  }, [likeCount, dislikeCount, myVote])

  const vote = async (value: 1 | -1) => {
    setBusy(true)
    try {
      const next = await onVote(value)
      setState({
        likeCount: next.like_count,
        dislikeCount: next.dislike_count,
        myVote: next.my_vote,
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Group gap={4}>
      <Button
        variant={state.myVote === 1 ? 'filled' : 'light'}
        size={size}
        loading={busy}
        aria-label="Like"
        aria-pressed={state.myVote === 1}
        onClick={() => vote(1)}
      >
        ♥ {state.likeCount}
      </Button>
      <Button
        variant={state.myVote === -1 ? 'filled' : 'light'}
        color="ink"
        size={size}
        loading={busy}
        aria-label="Dislike"
        aria-pressed={state.myVote === -1}
        onClick={() => vote(-1)}
      >
        ✕ {state.dislikeCount}
      </Button>
    </Group>
  )
}
