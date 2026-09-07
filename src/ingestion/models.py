from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from src.entities.enums import DocumentSourceType, DocumentStatus


class TableExtractResponse(BaseModel):
    page: int
    markdown: str


class DocumentResponse(BaseModel):
    id: UUID
    domain_id: UUID
    source_type: DocumentSourceType
    filename: str
    content_type: str | None
    status: DocumentStatus
    error_message: str | None
    ocr_used: bool
    author: str | None
    doc_created_at: datetime | None
    tables_extracted: list[TableExtractResponse] | None
    uploaded_by: UUID
    uploaded_at: datetime
