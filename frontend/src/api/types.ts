// TS mirrors of the backend pydantic schemas (backend/app/schemas/).

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface PostCreate {
  title: string
  body: string
  document_id?: number | null
  category?: string | null
}

export interface CommentOut {
  id: number
  author_email: string
  body: string
  created_at: string
  edited_at: string | null
}

export interface PostOut {
  id: number
  author_email: string
  title: string
  body: string
  category: string | null
  like_count: number
  created_at: string
}

export interface PostDetail extends PostOut {
  comments: CommentOut[]
}

export interface LikeResponse {
  like_count: number
  liked: boolean
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

export interface HistoryResponse {
  entries: HistoryEntryOut[]
}

export interface PreferenceItem {
  category: string
  weight: number
}

export interface PreferencesResponse {
  items: PreferenceItem[]
}
