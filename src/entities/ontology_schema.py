from sqlalchemy import Column, Boolean, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class OntologySchema(Base):
    __tablename__ = 'ontology_schemas'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey('domains.id'), nullable=False)

    version = Column(Integer, nullable=False)
    node_types = Column(JSON, nullable=False)
    relation_types = Column(JSON, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<OntologySchema(domain_id='{self.domain_id}', version={self.version}, active={self.is_active})>"
