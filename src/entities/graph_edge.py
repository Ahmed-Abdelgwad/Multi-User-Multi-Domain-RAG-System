from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class GraphEdge(Base):
    """A Subject -> Predicate -> Object relationship (spec 2.5) between two
    `GraphNode`s, constrained to the domain's active ontology
    (`OntologySchema.relation_types`). Deduped by exact match on
    `(domain_id, source_node_id, target_node_id, predicate)` -- a repeat
    extraction of the same triple from a different chunk doesn't insert a
    new edge; it's reflected as an additional `ChunkGraphEdgeLink` row and
    a recomputed `mention_count`.

    `mention_count` is not a manually incremented counter (that would
    drift if a chunk were ever re-processed) -- it's the count of distinct
    `ChunkGraphEdgeLink` rows for this edge, recomputed on every touch, so
    it always reflects exactly how many currently-linked chunks assert
    this relationship.
    """
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
