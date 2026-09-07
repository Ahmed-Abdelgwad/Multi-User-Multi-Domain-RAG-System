from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class ChunkGraphEdgeLink(Base):
    """Bidirectional-lookup junction (spec 2.5) for edges specifically --
    closes the gap a node-only link would leave open: without this,
    "which chunk asserted this relationship?" has no precise answer (you
    could only infer it indirectly via the source/target nodes' own chunk
    links, which is wrong whenever either node also appears, unrelated to
    this edge, in other chunks/documents). One row per (chunk, edge) pair;
    `GraphEdge.mention_count` is recomputed from the count of these rows
    every time one is added (see extraction/service.py).
    """
    __tablename__ = 'chunk_graph_edge_links'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_id = Column(UUID(as_uuid=True), ForeignKey('chunks.id'), nullable=False)
    graph_edge_id = Column(UUID(as_uuid=True), ForeignKey('graph_edges.id'), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint('chunk_id', 'graph_edge_id', name='uq_chunk_graph_edge_links_pair'),
    )

    def __repr__(self):
        return f"<ChunkGraphEdgeLink(chunk_id={self.chunk_id}, graph_edge_id={self.graph_edge_id})>"
