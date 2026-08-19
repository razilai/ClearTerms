import {
  ActionIcon,
  Button,
  Group,
  Indicator,
  Popover,
  ScrollArea,
  Stack,
  Text,
  UnstyledButton,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  notificationsKey,
} from '../api/notifications'
import type { NotificationOut } from '../api/types'
import { notificationLink, notificationText } from '../lib/notificationText'

/** Unread events, plus the history behind them.
 *
 * A toast is ephemeral — miss it or dismiss it and the event is gone — so the
 * bell opens the same feed as a list. It reads the query the toast hook is
 * already polling (same key), so the two observers share one cache entry and
 * this adds no second request.
 */
export function NotificationBell() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [opened, setOpened] = useState(false)

  const { data } = useQuery({
    queryKey: notificationsKey,
    queryFn: () => listNotifications(),
  })
  const items = data?.items ?? []
  const unreadCount = data?.unread_count ?? 0

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: notificationsKey })
  const markAll = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: invalidate,
  })

  // Opening the panel deliberately does not mark anything read: checking one
  // thing should not wipe the markers on everything else.
  const open = (n: NotificationOut) => {
    const link = notificationLink(n)
    if (n.read_at === null) {
      void markNotificationRead(n.id).then(invalidate)
    }
    setOpened(false)
    if (link) {
      navigate(link)
    }
  }

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position="bottom-end"
      width={340}
      shadow="md"
      withinPortal
    >
      <Popover.Target>
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
                ? `Notifications — ${unreadCount} unread`
                : 'Notifications'
            }
            onClick={() => setOpened((o) => !o)}
          >
            {/* Text glyph rather than an icon dependency: the app ships no icon
                library, and a bell is unambiguous. */}
            <span aria-hidden>🔔</span>
          </ActionIcon>
        </Indicator>
      </Popover.Target>
      <Popover.Dropdown p="xs">
        <Group justify="space-between" align="center" px="xs" pb="xs">
          <Text fw={600} size="sm">
            Notifications
          </Text>
          <Button
            variant="subtle"
            size="compact-xs"
            disabled={unreadCount === 0 || markAll.isPending}
            onClick={() => markAll.mutate()}
          >
            Mark all read
          </Button>
        </Group>
        {items.length === 0 ? (
          <Text c="dimmed" size="sm" px="xs" py="md">
            Nothing yet.
          </Text>
        ) : (
          <ScrollArea.Autosize mah={360}>
            <Stack gap={2}>
              {items.map((n) => (
                <UnstyledButton
                  key={n.id}
                  onClick={() => open(n)}
                  px="xs"
                  py={6}
                  style={{ borderRadius: 4 }}
                >
                  <Group gap="xs" wrap="nowrap" align="flex-start">
                    {/* Unread marker: a dot rather than a background tint, so a
                        long unread run does not read as one solid block. */}
                    <Text
                      c={n.read_at === null ? 'blue' : 'transparent'}
                      size="sm"
                      aria-hidden
                    >
                      ●
                    </Text>
                    <div>
                      <Text size="sm">
                        <Text span fw={600} size="sm">
                          {n.actor_email}
                        </Text>{' '}
                        {notificationText(n)}
                      </Text>
                      <Text c="dimmed" size="xs">
                        {new Date(n.created_at).toLocaleString()}
                      </Text>
                    </div>
                  </Group>
                </UnstyledButton>
              ))}
            </Stack>
          </ScrollArea.Autosize>
        )}
      </Popover.Dropdown>
    </Popover>
  )
}
