import type { NotificationOut } from '../api/types'

// The sentence that follows the actor's email in a toast. Pure so it can be
// read and checked on its own; the backend deliberately ships kind + value
// rather than prose, which keeps copy changes out of the API contract.
export function notificationText(n: NotificationOut): string {
  const title = n.post_title ?? 'your post'
  switch (n.kind) {
    case 'dm':
      return 'sent you a message'
    case 'post_comment':
      return `commented on «${title}»`
    case 'post_vote':
      return n.value === 1
        ? `liked your post «${title}»`
        : `disliked your post «${title}»`
    case 'comment_vote':
      return n.value === 1
        ? `liked your comment on «${title}»`
        : `disliked your comment on «${title}»`
  }
}

// Where clicking the notification goes. Exactly one of post_id and
// conversation_id is set by the backend; null means the target is gone (a post
// deleted between the poll and the click), and the caller should not navigate.
export function notificationLink(n: NotificationOut): string | null {
  if (n.conversation_id !== null) {
    return `/messages/${n.conversation_id}`
  }
  if (n.post_id !== null) {
    return `/forum/${n.post_id}`
  }
  return null
}
