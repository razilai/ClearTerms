import { notifications } from '@mantine/notifications'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  listNotifications,
  markNotificationRead,
  notificationsKey,
  NOTIFICATION_PAGE_SIZE,
} from '../api/notifications'
import { notificationLink, notificationText } from './notificationText'

// A poll that lands after a long idle tab can carry more events than fit on
// screen; past this many, the rest are summarised in one line.
const TOAST_BURST = 5

/** Polls the feed, toasts what is new, and returns the unread count.
 *
 * Mount once, in the app shell.
 */
export function useNotificationToasts(): number {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // The high-water mark of ids already toasted. A ref, not query state, on
  // purpose: React Query restores cached data on remount, and a remount — a
  // route change, or StrictMode's double mount in development — must not
  // re-toast events the user has already seen.
  const seen = useRef<number | null>(null)

  const { data } = useQuery({
    queryKey: notificationsKey,
    queryFn: () => listNotifications(NOTIFICATION_PAGE_SIZE),
    refetchInterval: 30_000,
  })

  useEffect(() => {
    if (!data) {
      return
    }
    const highest = data.items.reduce((max, n) => Math.max(max, n.id), 0)
    const watermark = seen.current
    seen.current = watermark === null ? highest : Math.max(watermark, highest)
    if (watermark === null) {
      // First successful poll: seed the mark and toast nothing. Logging in
      // after a busy weekend would otherwise bury the screen in toasts — the
      // bell badge is what reports a backlog.
      return
    }

    const fresh = data.items
      .filter((n) => n.id > watermark && n.read_at === null)
      .sort((a, b) => a.id - b.id)

    for (const n of fresh.slice(0, TOAST_BURST)) {
      const link = notificationLink(n)
      notifications.show({
        title: n.actor_email,
        message: notificationText(n),
        style: link ? { cursor: 'pointer' } : undefined,
        onClick: () => {
          void markNotificationRead(n.id).then(() =>
            queryClient.invalidateQueries({ queryKey: notificationsKey }),
          )
          if (link) {
            navigate(link)
          }
        },
      })
    }
    if (fresh.length > TOAST_BURST) {
      notifications.show({
        message: `+${fresh.length - TOAST_BURST} more notifications`,
      })
    }
  }, [data, navigate, queryClient])

  return data?.unread_count ?? 0
}
