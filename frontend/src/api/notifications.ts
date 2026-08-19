import { request, requestJson } from './client'
import type { MarkAllReadResponse, NotificationPage } from './types'

// Shared so the bell and the toast hook read the same cached poll, and so a
// mark-read anywhere invalidates both without either importing the other.
export const notificationsKey = ['notifications']

// One screen of recent events. The feed is polled, not browsed, so this is the
// only page size in play — there is no notification list UI to page through.
export const NOTIFICATION_PAGE_SIZE = 15

export function listNotifications(
  limit: number = NOTIFICATION_PAGE_SIZE,
  cursor?: string | null,
): Promise<NotificationPage> {
  const query = cursor
    ? `?limit=${limit}&cursor=${encodeURIComponent(cursor)}`
    : `?limit=${limit}`
  return request<NotificationPage>(`/notifications${query}`)
}

// Acknowledges one event — the toast click path.
export function markNotificationRead(notificationId: number): Promise<void> {
  return requestJson<void>(`/notifications/${notificationId}/read`, 'POST', {})
}

// Acknowledges everything — the bell click path.
export function markAllNotificationsRead(): Promise<MarkAllReadResponse> {
  return requestJson<MarkAllReadResponse>('/notifications/read', 'POST', {})
}
