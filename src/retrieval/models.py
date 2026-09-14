from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field
from src.entities.enums import LLMRoute
from src.evaluation.models import EvaluationSummary


class DomainRetrievalConfigResponse(BaseModel):
    domain_id: UUID
    dense_weight: float
    bm25_weight: float
    graph_weight: float
    entity_centric_ratio_threshold: float
    entity_centric_graph_boost: float
    llm_routing_default: LLMRoute
    llm_routing_sensitive_keywords: list[str]
    confidence_threshold: float
    updated_at: datetime


class DomainRetrievalConfigUpdate(BaseModel):
    # Spec 3.4's per-domain RRF signal weights + entity-centric routing
    # rule, 3.5's routing rule, and 3.6's confidence threshold --
    # validated together in the service layer (at least one weight must
    # be > 0, mirroring EnsembleRetriever's own validation) since that
    # rule spans fields.
    dense_weight: float = Field(ge=0.0)
    bm25_weight: float = Field(ge=0.0)
    graph_weight: float = Field(ge=0.0)
    entity_centric_ratio_threshold: float = Field(ge=0.0, le=1.0)
    entity_centric_graph_boost: float = Field(ge=0.0)
    llm_routing_default: LLMRoute
    llm_routing_sensitive_keywords: list[str] = Field(default_factory=list)
    confidence_threshold: float = Field(ge=0.0, le=1.0)


class QueryRequest(BaseModel):
    query: str
    domain_ids: list[UUID]


class QuerySource(BaseModel):
    chunk_id: str
    domain_id: str
    domain_name: str
    content_type: str
    score: float | None = None


class QueryResponse(BaseModel):
    answer: str
    route: LLMRoute
    confidence: float
    low_confidence: bool
    entities: list[tuple[str, str]]
    sources: list[QuerySource]
    query_log_id: UUID
    # Spec 4.3: "Evaluation scores included in the /query response
    # envelope (async -- may be null if evaluation not yet complete)".
    # Always null at response time by construction -- the judge task is
    # only just dispatched (see retrieval/service.py::answer_query); the
    # real value is only ever populated via GET /query/{id}/evaluation.
    evaluation: EvaluationSummary | None = None
