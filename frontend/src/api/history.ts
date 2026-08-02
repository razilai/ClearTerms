import { request } from './client'
import type { HistoryResponse } from './types'

export function getHistory(): Promise<HistoryResponse> {
  return request<HistoryResponse>('/history')
}
