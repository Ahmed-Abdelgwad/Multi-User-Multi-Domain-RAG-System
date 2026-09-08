from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base
from .enums import DocumentSourceType, DocumentStatus


class Document(Base):
    
    __tablename__ = 'documents'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey('domains.id'), nullable=False)

    source_type = Column(Enum(DocumentSourceType), nullable=False)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    storage_key = Column(String, nullable=False)

    status = Column(Enum(DocumentStatus), nullable=False, default=DocumentStatus.PENDING)
    error_message = Column(String, nullable=True)
    ocr_used = Column(Boolean, nullable=False, default=False)

    # Metadata extracted at ingest time (spec 2.1).
    author = Column(String, nullable=True)
    doc_created_at = Column(DateTime, nullable=True)

    # Populated by the extraction task; chunking (phase 3) reads from here
    # instead of re-parsing the raw file.
    extracted_text = Column(Text, nullable=True)


    tables_extracted = Column(JSON, nullable=True)

    # True reading-order element list ([{"kind": "text"|"table", "content": str}, ...]) --
    # the single source of truth chunking reads from (see chunking/service.py),
    # not extracted_text/tables_extracted (kept for display/metadata only).
    elements_extracted = Column(JSON, nullable=True)

    uploaded_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    uploaded_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Document(filename='{self.filename}', status={self.status})>"
