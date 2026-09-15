import { apiDelete, apiDownloadBlob, apiGet, apiPost, apiPut } from './client'
import type {
  EvaluationOverrideRequest,
  EvaluationVerdictRequest,
  GoldenQAItemCreate,
  GoldenQAItemResponse,
  ModerationQueueItemResponse,
  QualityDashboardResponse,
} from './types'

export function getQualityDashboard(
  domainId: string,
  windowDays: number,
  trendPoints: number,
): Promise<QualityDashboardResponse> {
  return apiGet<QualityDashboardResponse>(
    `/domains/${domainId}/quality-dashboard/?window_days=${windowDays}&trend_points=${trendPoints}`,
  )
}

export function downloadQualityDashboardCsv(domainId: string, windowDays: number, trendPoints: number): Promise<Blob> {
  return apiDownloadBlob(
    `/domains/${domainId}/quality-dashboard/export?window_days=${windowDays}&trend_points=${trendPoints}`,
  )
}

export function getModerationQueue(domainId: string): Promise<ModerationQueueItemResponse[]> {
  return apiGet<ModerationQueueItemResponse[]>(`/domains/${domainId}/moderation-queue/`)
}

export function overrideEvaluation(
  domainId: string,
  queryLogId: string,
  payload: EvaluationOverrideRequest,
): Promise<ModerationQueueItemResponse> {
  return apiPost(`/domains/${domainId}/moderation-queue/${queryLogId}/override`, payload)
}

export function setEvaluationVerdict(
  domainId: string,
  queryLogId: string,
  payload: EvaluationVerdictRequest,
): Promise<ModerationQueueItemResponse> {
  return apiPost(`/domains/${domainId}/moderation-queue/${queryLogId}/verdict`, payload)
}

export function listGoldenQaItems(domainId: string): Promise<GoldenQAItemResponse[]> {
  return apiGet<GoldenQAItemResponse[]>(`/domains/${domainId}/golden-qa/`)
}

export function createGoldenQaItem(domainId: string, payload: GoldenQAItemCreate): Promise<GoldenQAItemResponse> {
  return apiPost<GoldenQAItemResponse>(`/domains/${domainId}/golden-qa/`, payload)
}

export function updateGoldenQaItem(
  domainId: string,
  itemId: string,
  payload: GoldenQAItemCreate,
): Promise<GoldenQAItemResponse> {
  return apiPut<GoldenQAItemResponse>(`/domains/${domainId}/golden-qa/${itemId}`, payload)
}

export function deleteGoldenQaItem(domainId: string, itemId: string): Promise<void> {
  return apiDelete<void>(`/domains/${domainId}/golden-qa/${itemId}`)
}

export function triggerGoldenRegression(domainId: string): Promise<{ status: string }> {
  return apiPost<{ status: string }>(`/domains/${domainId}/golden-qa/run-regression`)
}
