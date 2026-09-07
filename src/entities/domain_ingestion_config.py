from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class DomainIngestionConfig(Base):
    """Per-domain Paragraph Group Chunking parameters (spec 2.4:
    "configurable ... per domain"). One row per domain, created lazily
    with defaults on first read (see chunking/service.py) rather than at
    domain-creation time, so a domain that never touches ingestion never
    needs one.
    """
    __tablename__ = 'domain_ingestion_configs'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey('domains.id'), nullable=False, unique=True)

    # PGC's G (paragraphs grouped per chunk) and O (paragraph overlap
    # between consecutive chunks) -- see chunking/chunker.py. Defaults are
    # the paper's own formal spec (Table 2: G=2, O=1), chosen in the
    # section-2 plan's literature review.
    paragraphs_per_chunk = Column(Integer, nullable=False, default=2)
    paragraph_overlap = Column(Integer, nullable=False, default=1)

    updated_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<DomainIngestionConfig(domain_id='{self.domain_id}', G={self.paragraphs_per_chunk}, O={self.paragraph_overlap})>"
