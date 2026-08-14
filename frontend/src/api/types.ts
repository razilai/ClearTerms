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
  attachment_ids?: number[]
}

export interface CommentOut {
  id: number
  author_email: string
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
  author_email: string
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

export interface PreferenceItem {
  category: string
  weight: number
}

export interface PreferencesResponse {
  items: PreferenceItem[]
}
