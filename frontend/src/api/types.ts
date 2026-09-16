// Mirrors src/entities/enums.py and the pydantic response models in
// src/*/models.py. Kept as one file since every feature area's types are
// small and this avoids a type-import maze across api/*.ts.

export type DomainRole = 'reader' | 'contributor' | 'domain_admin'
export type LLMRoute = 'local' | 'api'
export type JudgeProvider = 'mercury' | 'ollama'
export type EvaluationStatus = 'pending' | 'completed' | 'failed' | 'skipped'
export type HumanVerdict = 'accepted' | 'rejected'
export type DocumentStatus = 'pending' | 'processing' | 'indexing' | 'ready' | 'failed'
export type DocumentSourceType = 'pdf' | 'docx' | 'csv' | 'xlsx' | 'web' | 'db'
export type ChunkContentType = 'text' | 'table'

export interface UserResponse {
  id: string
  email: string
  first_name: string
  last_name: string
  is_platform_admin: boolean
}

export interface UserDomainMembership {
  domain_id: string
  domain_name: string
  role: DomainRole
  granted_at: string
}

export interface DomainResponse {
  id: string
  name: string
  description: string | null
  is_archived: boolean
  created_by: string
  created_at: string
}

export interface UserDomainRoleResponse {
  user_id: string
  domain_id: string
  role: DomainRole
  granted_at: string
  user_email: string | null
}

export interface TableExtractResponse {
  page: number
  markdown: string
}

export interface DocumentResponse {
  id: string
  domain_id: string
  source_type: DocumentSourceType
  filename: string
  content_type: string | null
  status: DocumentStatus
  error_message: string | null
  ocr_used: boolean
  author: string | null
  doc_created_at: string | null
  tables_extracted: TableExtractResponse[] | null
  uploaded_by: string
  uploaded_at: string
}

export interface ChunkResponse {
  id: string
  document_id: string
  domain_id: string
  content: string
  content_type: ChunkContentType
  chunk_index: number
  embedding_model_version: string | null
  is_active: boolean
  created_at: string
}

export interface QuerySource {
  chunk_id: string
  domain_id: string
  domain_name: string
  content_type: string
  score: number | null
}

export interface EvaluationSummary {
  status: EvaluationStatus
  faithfulness: number | null
  relevance: number | null
  completeness: number | null
  citation_accuracy: number | null
  flagged: boolean
}

export interface QueryResponse {
  answer: string
  route: LLMRoute
  confidence: number
  low_confidence: boolean
  entities: [string, string][]
  sources: QuerySource[]
  query_log_id: string
  evaluation: EvaluationSummary | null
}

export interface EvaluationDetailResponse {
  query_log_id: string
  status: EvaluationStatus
  faithfulness: number | null
  relevance: number | null
  completeness: number | null
  citation_accuracy: number | null
  rationale: Record<string, string> | null
  flagged: boolean
  judge_provider: JudgeProvider | null
  judge_model_version: string | null
  error_message: string | null
  overridden_by: string | null
  override_rationale: string | null
  overridden_at: string | null
  original_scores: Record<string, number | null> | null
  human_verdict: HumanVerdict | null
}

export interface ModerationQueueItemResponse extends EvaluationDetailResponse {
  query: string
  answer: string
  query_created_at: string
}

export interface EvaluationOverrideRequest {
  faithfulness: number
  relevance: number
  completeness: number
  citation_accuracy: number
  rationale: string
}

export interface EvaluationVerdictRequest {
  verdict: HumanVerdict
  rationale: string
}

export interface QualityDashboardDimension {
  mean: number | null
  sample_count: number
}

export interface QualityDashboardTrendPoint {
  period_start: string
  period_end: string
  by_dimension: Record<string, QualityDashboardDimension>
}

export interface GoldenRegressionSummary {
  item_count: number
  flagged_count: number
  last_run_at: string | null
  by_dimension: Record<string, QualityDashboardDimension>
}

export interface QualityDashboardResponse {
  domain_id: string
  window_days: number
  by_dimension: Record<string, QualityDashboardDimension>
  by_route: Record<string, Record<string, QualityDashboardDimension>>
  degrading_dimensions: string[]
  trend: QualityDashboardTrendPoint[]
  golden_regression: GoldenRegressionSummary
}

export interface GoldenQAItemResponse {
  id: string
  domain_id: string
  question: string
  expected_answer: string
  expected_citations: string[]
  created_by: string
  created_at: string
  updated_at: string
}

export interface GoldenQAItemCreate {
  question: string
  expected_answer: string
  expected_citations: string[]
}
