from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field
from src.entities.enums import ChunkContentType


class ChunkResponse(BaseModel):
    id: UUID
    document_id: UUID
    domain_id: UUID
    content: str
    content_type: ChunkContentType
    chunk_index: int
    embedding_model_version: str | None
    is_active: bool
    created_at: datetime


class DomainIngestionConfigResponse(BaseModel):
    domain_id: UUID
    paragraphs_per_chunk: int
    paragraph_overlap: int
    updated_at: datetime


class DomainIngestionConfigUpdate(BaseModel):
    # Spec 2.4's PGC: G (paragraphs_per_chunk) and O (paragraph_overlap),
    # per-domain (see DomainIngestionConfig). Bounds are validated again in
    # the service layer (overlap must be < paragraphs_per_chunk) since that
    # rule spans both fields together.
    paragraphs_per_chunk: int = Field(ge=1)
    paragraph_overlap: int = Field(ge=0)
