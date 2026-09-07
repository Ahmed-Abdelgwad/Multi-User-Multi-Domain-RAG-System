from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector
import uuid
from datetime import datetime, timezone
from ..database.core import Base
from .enums import ChunkContentType

# Fixed once for the whole project (spec 2.4: the embedding model choice
# must be fixed at project start to avoid costly re-indexing) -- see
# chunking/embeddings.py for the actual model (currently
# ibm-granite/granite-embedding-97m-multilingual-r2) and the RAM-driven
# reasoning behind picking it. The column's dimension has to match its
# output size exactly -- verified against the model's own HF page, not
# assumed.
EMBEDDING_DIM = 384


class Chunk(Base):
    """A single retrievable unit produced by Paragraph Group Chunking
    (spec 2.4), always domain-scoped like `Document`. `is_active` lets a
    re-chunk/re-embed pass (e.g. after an embedding model upgrade) write a
    fresh generation of chunks without deleting the old ones until the
    new generation is confirmed good -- spec 2.4's versioning requirement.
    """
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

    # Spec 2.5: NULL until phase 7's periodic batch extraction task has
    # processed this chunk (or after an ontology-version change resets it
    # back to NULL -- see ontology/service.py's reextract trigger and
    # tasks/pipeline.py's batch_extract_entities_task). Not meant to be
    # read outside the extraction pipeline itself.
    entities_extracted_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Chunk(document_id='{self.document_id}', index={self.chunk_index}, type={self.content_type})>"
