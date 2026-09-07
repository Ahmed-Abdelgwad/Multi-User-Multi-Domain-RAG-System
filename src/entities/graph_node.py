from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, JSON, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class GraphNode(Base):
    """An entity in the domain's knowledge graph (spec 2.5), extracted from
    chunk text and constrained to the domain's active ontology
    (`OntologySchema.node_types`). Deduped across chunks/documents by
    exact match on `(domain_id, type, name_key)` -- `name_key` is the
    case-insensitive, whitespace-trimmed form of `name` used purely for
    matching; `name` keeps the first-seen casing for display. Mirrors
    GraphRAG's own entity-resolution simplification (see the plan's
    GraphRAG cross-check) rather than fuzzy matching.

    `description` accumulates text from every occurrence instead of being
    overwritten (same cross-check). `ontology_version`/
    `extractor_model_version` are stamped on every touch (new row or
    re-matched existing one) so a future ontology or model upgrade can
    identify exactly which nodes are stale and need re-extraction.
    """
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
