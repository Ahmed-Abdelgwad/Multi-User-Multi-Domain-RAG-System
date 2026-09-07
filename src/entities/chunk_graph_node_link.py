from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class ChunkGraphNodeLink(Base):
    
    __tablename__ = 'chunk_graph_node_links'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_id = Column(UUID(as_uuid=True), ForeignKey('chunks.id'), nullable=False)
    graph_node_id = Column(UUID(as_uuid=True), ForeignKey('graph_nodes.id'), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint('chunk_id', 'graph_node_id', name='uq_chunk_graph_node_links_pair'),
    )

    def __repr__(self):
        return f"<ChunkGraphNodeLink(chunk_id={self.chunk_id}, graph_node_id={self.graph_node_id})>"
