import { apiGet, apiPost } from './client'
import type { EvaluationDetailResponse, QueryResponse } from './types'

export function submitQuery(query: string, domainIds: string[]): Promise<QueryResponse> {
  return apiPost<QueryResponse>('/query/', { query, domain_ids: domainIds })
}

export function getQueryEvaluation(queryLogId: string): Promise<EvaluationDetailResponse> {
  return apiGet<EvaluationDetailResponse>(`/query/${queryLogId}/evaluation`)
}
