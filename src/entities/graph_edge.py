from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class GraphEdge(Base):
    
    __tablename__ = 'graph_edges'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey('domains.id'), nullable=False)
    source_node_id = Column(UUID(as_uuid=True), ForeignKey('graph_nodes.id'), nullable=False)
    target_node_id = Column(UUID(as_uuid=True), ForeignKey('graph_nodes.id'), nullable=False)

    predicate = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    mention_count = Column(Integer, nullable=False, default=0)

    ontology_version = Column(Integer, nullable=False)
    extractor_model_version = Column(String, nullable=False)

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint('domain_id', 'source_node_id', 'target_node_id', 'predicate', name='uq_graph_edges_triple'),
    )

    def __repr__(self):
        return f"<GraphEdge(predicate='{self.predicate}', source={self.source_node_id}, target={self.target_node_id})>"
