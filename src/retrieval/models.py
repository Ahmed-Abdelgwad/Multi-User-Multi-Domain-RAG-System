from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field
from src.entities.enums import LLMRoute


class DomainRetrievalConfigResponse(BaseModel):
    domain_id: UUID
    dense_weight: float
    bm25_weight: float
    graph_weight: float
    llm_routing_default: LLMRoute
    llm_routing_sensitive_keywords: list[str]
    confidence_threshold: float
    updated_at: datetime


class DomainRetrievalConfigUpdate(BaseModel):
    # Spec 3.4's per-domain RRF signal weights, 3.5's routing rule, and
    # 3.6's confidence threshold -- validated together in the service
    # layer (at least one weight must be > 0, mirroring
    # EnsembleRetriever's own validation) since that rule spans fields.
    dense_weight: float = Field(ge=0.0)
    bm25_weight: float = Field(ge=0.0)
    graph_weight: float = Field(ge=0.0)
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
