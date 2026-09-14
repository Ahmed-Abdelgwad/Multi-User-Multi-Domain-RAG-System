from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field
from src.entities.enums import EvaluationStatus, JudgeProvider


class DomainEvaluationConfigResponse(BaseModel):
    domain_id: UUID
    flag_threshold: float
    degradation_alert_threshold: float
    updated_at: datetime


class DomainEvaluationConfigUpdate(BaseModel):
    flag_threshold: float = Field(ge=0.0, le=1.0)
    degradation_alert_threshold: float = Field(ge=0.0, le=1.0)


class EvaluationSummary(BaseModel):
    """Spec 4.3's literal "may be null if evaluation not yet complete" --
    embedded in /query's response envelope, always null at response time
    since the judge task has only just been dispatched (see
    retrieval/controller.py::query).
    """
    status: EvaluationStatus
    faithfulness: float | None = None
    relevance: float | None = None
    completeness: float | None = None
    citation_accuracy: float | None = None
    flagged: bool = False


class EvaluationDetailResponse(BaseModel):
    query_log_id: UUID
    status: EvaluationStatus
    faithfulness: float | None
    relevance: float | None
    completeness: float | None
    citation_accuracy: float | None
    rationale: dict[str, str] | None
    flagged: bool
    judge_provider: JudgeProvider | None
    judge_model_version: str | None
    error_message: str | None
    overridden_by: UUID | None
    override_rationale: str | None
    overridden_at: datetime | None


class EvaluationOverrideRequest(BaseModel):
    faithfulness: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    completeness: float = Field(ge=0.0, le=1.0)
    citation_accuracy: float = Field(ge=0.0, le=1.0)
    rationale: str


class GoldenQAItemResponse(BaseModel):
    id: UUID
    domain_id: UUID
    question: str
    expected_answer: str
    expected_citations: list[str]
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class GoldenQAItemCreate(BaseModel):
    question: str
    expected_answer: str
    expected_citations: list[str] = Field(default_factory=list)


class QualityDashboardDimension(BaseModel):
    mean: float | None
    sample_count: int


class QualityDashboardResponse(BaseModel):
    domain_id: UUID
    window_days: int
    by_dimension: dict[str, QualityDashboardDimension]
    by_route: dict[str, dict[str, QualityDashboardDimension]]
    degrading_dimensions: list[str]
