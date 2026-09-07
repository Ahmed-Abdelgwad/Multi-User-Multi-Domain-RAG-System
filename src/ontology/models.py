from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class RelationTypeSpec(BaseModel):
    # Spec 2.5's Subject -> Predicate -> Object triple, declared ahead of
    # time here: `name` is the predicate, `source_type`/`target_type` must
    # each be one of the schema's own `node_types`.
    name: str
    source_type: str
    target_type: str


class OntologySchemaCreate(BaseModel):
    node_types: list[str] = Field(min_length=1)
    relation_types: list[RelationTypeSpec] = Field(default_factory=list)


class OntologySchemaResponse(BaseModel):
    id: UUID
    domain_id: UUID
    version: int
    node_types: list[str]
    relation_types: list[RelationTypeSpec]
    is_active: bool
    created_by: UUID | None
    created_at: datetime
