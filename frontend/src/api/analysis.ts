import { request, requestJson } from './client'
import type { AnalyzeRequest, AnalysisDetail, VerdictResponse } from './types'

export function analyze(body: AnalyzeRequest): Promise<VerdictResponse> {
  return requestJson<VerdictResponse>('/analyze', 'POST', body)
}

export function getAnalysis(analysisId: number): Promise<AnalysisDetail> {
  return request<AnalysisDetail>(`/analyses/${analysisId}`)
}
