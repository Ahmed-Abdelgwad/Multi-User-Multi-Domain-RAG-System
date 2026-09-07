from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class DomainIngestionConfig(Base):
    
    __tablename__ = 'domain_ingestion_configs'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey('domains.id'), nullable=False, unique=True)

    paragraphs_per_chunk = Column(Integer, nullable=False, default=2)
    paragraph_overlap = Column(Integer, nullable=False, default=1)

    updated_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<DomainIngestionConfig(domain_id='{self.domain_id}', G={self.paragraphs_per_chunk}, O={self.paragraph_overlap})>"
