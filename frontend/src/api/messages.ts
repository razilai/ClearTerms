import { request, requestJson } from './client'
import type {
  ConversationDetail,
  ConversationOut,
  MarkReadResponse,
  MessageOut,
  Page,
  UnreadTotal,
} from './types'

// Query keys shared across the section: the composer invalidates the inbox and
// the nav badge without either of them importing the other. They live here
// rather than in a page so a component file only exports components.
export const conversationsKey = ['conversations']
export const unreadKey = ['messages', 'unread']

// One keyset page of the inbox, most recent activity first.
export function listConversations(
  limit: number,
  cursor?: string | null,
): Promise<Page<ConversationOut>> {
  const query = cursor
    ? `?limit=${limit}&cursor=${encodeURIComponent(cursor)}`
    : `?limit=${limit}`
  return request<Page<ConversationOut>>(`/messages/conversations${query}`)
}

// Idempotent: returns the existing thread with this person if there is one, so
// this doubles as "open the conversation with X".
export function startConversation(
  recipientEmail: string,
): Promise<ConversationOut> {
  return requestJson<ConversationOut>('/messages/conversations', 'POST', {
    recipient_email: recipientEmail,
  })
}

// The thread plus its first page of messages, in one request.
export function getConversation(
  conversationId: number,
): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/messages/conversations/${conversationId}`)
}

// Older pages of a thread (the first ships inside ConversationDetail).
export function listMessages(
  conversationId: number,
  limit: number,
  cursor?: string | null,
): Promise<Page<MessageOut>> {
  const query = cursor
    ? `?limit=${limit}&cursor=${encodeURIComponent(cursor)}`
    : `?limit=${limit}`
  return request<Page<MessageOut>>(
    `/messages/conversations/${conversationId}/messages${query}`,
  )
}

export function sendMessage(
  conversationId: number,
  body: string,
): Promise<MessageOut> {
  return requestJson<MessageOut>(
    `/messages/conversations/${conversationId}/messages`,
    'POST',
    { body },
  )
}

// Clears the other party's unread messages in this thread.
export function markRead(conversationId: number): Promise<MarkReadResponse> {
  return requestJson<MarkReadResponse>(
    `/messages/conversations/${conversationId}/read`,
    'POST',
    {},
  )
}

export function getUnreadTotal(): Promise<UnreadTotal> {
  return request<UnreadTotal>('/messages/unread')
}
