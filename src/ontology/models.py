from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


def _normalize_type_specs(value):
    
    if not isinstance(value, list):
        return value
    return [{"name": v} if isinstance(v, str) else v for v in value]


class NodeTypeSpec(BaseModel):
    
    name: str
    description: str | None = None
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class RelationTypeSpec(BaseModel):
    name: str
    source_type: str
    target_type: str
    description: str | None = None
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class OntologySchemaCreate(BaseModel):
    node_types: list[NodeTypeSpec] = Field(min_length=1)
    relation_types: list[RelationTypeSpec] = Field(default_factory=list)

    @field_validator("node_types", mode="before")
    @classmethod
    def _normalize_node_types(cls, value):
        return _normalize_type_specs(value)


class OntologySchemaResponse(BaseModel):
    id: UUID
    domain_id: UUID
    version: int
    node_types: list[NodeTypeSpec]
    relation_types: list[RelationTypeSpec]
    is_active: bool
    created_by: UUID | None
    created_at: datetime

    @field_validator("node_types", mode="before")
    @classmethod
    def _normalize_node_types(cls, value):
        return _normalize_type_specs(value)
