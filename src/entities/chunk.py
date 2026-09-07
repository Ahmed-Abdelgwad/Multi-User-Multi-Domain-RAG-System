from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector
import uuid
from datetime import datetime, timezone
from ..database.core import Base
from .enums import ChunkContentType

EMBEDDING_DIM = 384


class Chunk(Base):
    
    __tablename__ = 'chunks'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.id'), nullable=False)
    domain_id = Column(UUID(as_uuid=True), ForeignKey('domains.id'), nullable=False)

    content = Column(Text, nullable=False)
    content_type = Column(Enum(ChunkContentType), nullable=False, default=ChunkContentType.TEXT)
    chunk_index = Column(Integer, nullable=False)

    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model_version = Column(String, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    
    entities_extracted_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Chunk(document_id='{self.document_id}', index={self.chunk_index}, type={self.content_type})>"
