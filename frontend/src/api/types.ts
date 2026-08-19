// TS mirrors of the backend pydantic schemas (backend/app/schemas/).

export interface TokenResponse {
  access_token: string
  token_type: string
}

export type AttachmentStatus = 'pending' | 'ready' | 'failed'
export type MediaType = 'image' | 'video'

export interface AttachmentOut {
  id: number
  media_type: MediaType
  status: AttachmentStatus
  mime: string
  width: number | null
  height: number | null
  duration_seconds: number | null
  display_url: string | null
  thumbnail_url: string | null
}

export interface PostCreate {
  title: string
  body: string
  document_id?: number | null
  is_anonymous?: boolean
  attachment_ids?: number[]
}

export interface CommentOut {
  id: number
  // True for the author of an anonymous post commenting under it; author_email
  // is then null for everyone but them.
  is_anonymous: boolean
  author_email: string | null
  body: string
  created_at: string
  edited_at: string | null
  like_count: number
  dislike_count: number
  // This user's own vote: -1, 0 or 1.
  my_vote: number
  attachments: AttachmentOut[]
}

export interface PostOut {
  id: number
  // null on an anonymous post unless you are its author.
  author_email: string | null
  is_anonymous: boolean
  title: string
  body: string
  like_count: number
  dislike_count: number
  my_vote: number
  created_at: string
  attachments: AttachmentOut[]
}

export interface PostDetail extends PostOut {
  // First keyset page of comments; fetch more with listComments + this cursor.
  comments: CommentOut[]
  comments_next_cursor: string | null
}

// Keyset-paginated list envelope (mirror of app.schemas.pagination.Page).
// next_cursor is null on the last page; pass it back to fetch the next one.
export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

// Totals across everything you ever wrote — not just the page on screen.
// Posts and comments are tallied separately; the personal area shows a box each.
export interface MyVoteTotals {
  post_count: number
  like_count: number
  dislike_count: number
  comment_count: number
  comment_like_count: number
  comment_dislike_count: number
}

export interface VoteResponse {
  like_count: number
  dislike_count: number
  my_vote: number
}

export interface AnalyzeRequest {
  text: string
  url?: string | null
}

export interface VerdictResponse {
  verdict: string
  analysis_id: number
}

export interface FindingOut {
  evidence: string
  score: number
  explanation: string
}

export interface CategoryScore {
  category: string
  score: number
  // Every clause found for this category; score is their max. Always present,
  // empty for a category the document does not address.
  findings: FindingOut[]
}

export interface AnalysisDetail {
  id: number
  url: string | null
  scores: CategoryScore[]
  model_version: string
  created_at: string
}

export interface HistoryEntryOut {
  document_id: number
  url: string | null
  verdict: string
  created_at: string
}

export interface MessageOut {
  id: number
  conversation_id: number
  sender_email: string
  body: string
  created_at: string
  // Set once the other party opened the thread; always null on messages you
  // received, since reading them is what clears it.
  read_at: string | null
  attachments: AttachmentOut[]
}

export interface ConversationOut {
  id: number
  // The participant who is not you — the server never sends both sides.
  other_email: string
  last_message_at: string
  created_at: string
  // Newest message, for the inbox preview; null on a thread nobody has
  // written in yet.
  last_message: MessageOut | null
  unread_count: number
}

export interface ConversationDetail extends ConversationOut {
  // First page of messages, newest first (reverse for display).
  messages: MessageOut[]
  messages_next_cursor: string | null
}

export interface UnreadTotal {
  unread_count: number
}

export interface MarkReadResponse {
  marked_count: number
}

export interface PreferenceItem {
  category: string
  enabled: boolean
}

export interface PreferencesResponse {
  items: PreferenceItem[]
}

// Mirrors app/schemas/notifications.py. The backend ships kind + value rather
// than a rendered sentence, so display copy stays a frontend concern.
export type NotificationKind =
  | 'dm'
  | 'post_comment'
  | 'post_vote'
  | 'comment_vote'

export interface NotificationOut {
  id: number
  kind: NotificationKind
  actor_email: string
  value: number | null
  post_id: number | null
  post_title: string | null
  conversation_id: number | null
  created_at: string
  read_at: string | null
}

// A Page<NotificationOut> plus the unread total, so one poll feeds both the
// toasts and the bell badge.
export interface NotificationPage extends Page<NotificationOut> {
  unread_count: number
}

export interface MarkAllReadResponse {
  marked_count: number
}

// Mirrors app/schemas/forum.py::VoterOut. Owner-only: the API returns this
// list to the author of the voted-on post or comment and 403s everyone else.
export interface VoterOut {
  email: string
  value: number
}
