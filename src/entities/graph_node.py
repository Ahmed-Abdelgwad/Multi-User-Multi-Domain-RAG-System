from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, JSON, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class GraphNode(Base):
    
    __tablename__ = 'graph_nodes'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey('domains.id'), nullable=False)

    type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    name_key = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    properties = Column(JSON, nullable=True)

    ontology_version = Column(Integer, nullable=False)
    extractor_model_version = Column(String, nullable=False)

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint('domain_id', 'type', 'name_key', name='uq_graph_nodes_domain_type_name_key'),
    )

    def __repr__(self):
        return f"<GraphNode(type='{self.type}', name='{self.name}')>"
