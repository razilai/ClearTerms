import { request, requestForm, requestJson } from './client'
import type {
  AttachmentOut,
  CommentOut,
  MyVoteTotals,
  Page,
  PostCreate,
  PostDetail,
  PostOut,
  VoteResponse,
} from './types'

// One keyset page of posts, newest first. Pass the previous page's next_cursor
// for the next page; omit for the first.
export function listPosts(cursor?: string | null): Promise<Page<PostOut>> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  return request<Page<PostOut>>(`/forum/posts${query}`)
}

// The personal area's own posts, a fixed page at a time.
export function listMyPosts(
  limit: number,
  cursor?: string | null,
): Promise<Page<PostOut>> {
  const query = cursor
    ? `?limit=${limit}&cursor=${encodeURIComponent(cursor)}`
    : `?limit=${limit}`
  return request<Page<PostOut>>(`/forum/posts/mine${query}`)
}

export function getMyVoteTotals(): Promise<MyVoteTotals> {
  return request<MyVoteTotals>('/forum/me/vote-totals')
}

export function getPost(postId: number): Promise<PostDetail> {
  return request<PostDetail>(`/forum/posts/${postId}`)
}

// Further pages of a post's comments (the first page ships inside PostDetail).
export function listComments(
  postId: number,
  cursor?: string | null,
): Promise<Page<CommentOut>> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  return request<Page<CommentOut>>(`/forum/posts/${postId}/comments${query}`)
}

export function createPost(body: PostCreate): Promise<PostOut> {
  return requestJson<PostOut>('/forum/posts', 'POST', body)
}

export function deletePost(postId: number): Promise<void> {
  return request<void>(`/forum/posts/${postId}`, { method: 'DELETE' })
}

export function addComment(postId: number, body: string): Promise<CommentOut> {
  return requestJson<CommentOut>(`/forum/posts/${postId}/comments`, 'POST', { body })
}

export function editComment(commentId: number, body: string): Promise<CommentOut> {
  return requestJson<CommentOut>(`/forum/comments/${commentId}`, 'PATCH', { body })
}

export function deleteComment(commentId: number): Promise<void> {
  return request<void>(`/forum/comments/${commentId}`, { method: 'DELETE' })
}

// Sending the value you already hold clears the vote (the server toggles).
export function votePost(postId: number, value: 1 | -1): Promise<VoteResponse> {
  return requestJson<VoteResponse>(`/forum/posts/${postId}/vote`, 'PUT', { value })
}

export function voteComment(
  commentId: number,
  value: 1 | -1,
): Promise<VoteResponse> {
  return requestJson<VoteResponse>(`/forum/comments/${commentId}/vote`, 'PUT', {
    value,
  })
}

export function uploadAttachment(file: File): Promise<AttachmentOut> {
  const fd = new FormData()
  fd.append('file', file)
  return requestForm<AttachmentOut>('/forum/attachments', fd)
}

export function getAttachment(attachmentId: number): Promise<AttachmentOut> {
  return request<AttachmentOut>(`/forum/attachments/${attachmentId}`)
}

export function addCommentWithAttachments(
  postId: number,
  body: string,
  attachmentIds: number[],
): Promise<CommentOut> {
  return requestJson<CommentOut>(`/forum/posts/${postId}/comments`, 'POST', {
    body,
    attachment_ids: attachmentIds,
  })
}
