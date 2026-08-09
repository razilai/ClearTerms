import { request, requestJson } from './client'
import type {
  CommentOut,
  LikeResponse,
  Page,
  PostCreate,
  PostDetail,
  PostOut,
} from './types'

// One keyset page of posts, newest first. Pass the previous page's next_cursor
// for the next page; omit for the first.
export function listPosts(cursor?: string | null): Promise<Page<PostOut>> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  return request<Page<PostOut>>(`/forum/posts${query}`)
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

export function toggleLike(postId: number): Promise<LikeResponse> {
  return request<LikeResponse>(`/forum/posts/${postId}/like`, { method: 'PUT' })
}
