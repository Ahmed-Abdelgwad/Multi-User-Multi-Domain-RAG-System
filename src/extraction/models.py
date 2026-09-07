from uuid import UUID
from datetime import datetime
from pydantic import BaseModel


class GraphNodeResponse(BaseModel):
    id: UUID
    domain_id: UUID
    type: str
    name: str
    description: str | None
    ontology_version: int
    extractor_model_version: str
    created_at: datetime
    updated_at: datetime


class GraphEdgeResponse(BaseModel):
    id: UUID
    domain_id: UUID
    source_node_id: UUID
    target_node_id: UUID
    predicate: str
    description: str | None
    mention_count: int
    ontology_version: int
    extractor_model_version: str
    created_at: datetime
    updated_at: datetime
