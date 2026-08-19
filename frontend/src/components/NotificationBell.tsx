import { ActionIcon, Indicator } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { markAllNotificationsRead, notificationsKey } from '../api/notifications'

interface NotificationBellProps {
  unreadCount: number
}

/** Unread events, acknowledged in one click.
 *
 * There is no dropdown: the toast is how an event is read, and this is the
 * catch-up affordance for events whose toast was missed.
 */
export function NotificationBell({ unreadCount }: NotificationBellProps) {
  const queryClient = useQueryClient()
  const markAll = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: notificationsKey }),
  })

  return (
    <Indicator
      label={unreadCount > 0 ? unreadCount : undefined}
      disabled={unreadCount === 0}
      size={16}
      offset={4}
    >
      <ActionIcon
        variant="subtle"
        color="ink"
        size="lg"
        aria-label={
          unreadCount > 0
            ? `${unreadCount} unread notifications — mark all read`
            : 'Notifications'
        }
        disabled={unreadCount === 0 || markAll.isPending}
        onClick={() => markAll.mutate()}
      >
        {/* Text glyph rather than an icon dependency: the app ships no icon
            library, and a bell is unambiguous. */}
        <span aria-hidden>🔔</span>
      </ActionIcon>
    </Indicator>
  )
}
