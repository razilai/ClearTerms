import { request, requestJson } from './client'
import type {
  CommentOut,
  LikeResponse,
  PostCreate,
  PostDetail,
  PostOut,
} from './types'

export function listPosts(): Promise<PostOut[]> {
  return request<PostOut[]>('/forum/posts')
}

export function getPost(postId: number): Promise<PostDetail> {
  return request<PostDetail>(`/forum/posts/${postId}`)
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
