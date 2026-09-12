import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from src.entities.chunk import Chunk
from src.entities.document import Document
from src.entities.domain_ingestion_config import DomainIngestionConfig
from src.entities.enums import ChunkContentType, DocumentStatus
from src.exceptions import InvalidIngestionConfigError
from src.ingestion.service import get_document_or_raise
from . import models


def get_or_create_ingestion_config(db: Session, domain_id: UUID) -> DomainIngestionConfig:
    """Lazily creates a domain's PGC config row with defaults (G=2, O=1 --
    the paper's own formal spec) the first time it's read, rather than at
    domain-creation time -- a domain that never touches ingestion never
    needs one.
    """
    config = db.query(DomainIngestionConfig).filter(DomainIngestionConfig.domain_id == domain_id).first()
    if config:
        return config

    config = DomainIngestionConfig(id=uuid4(), domain_id=domain_id)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_ingestion_config(
    db: Session, domain_id: UUID, update: models.DomainIngestionConfigUpdate, updated_by: UUID
) -> DomainIngestionConfig:
    if update.paragraph_overlap >= update.paragraphs_per_chunk:
        raise InvalidIngestionConfigError("paragraph_overlap must be less than paragraphs_per_chunk")

    config = get_or_create_ingestion_config(db, domain_id)
    config.paragraphs_per_chunk = update.paragraphs_per_chunk
    config.paragraph_overlap = update.paragraph_overlap
    config.updated_by = updated_by
    config.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(config)
    logging.info(f"Ingestion config for domain {domain_id} updated by {updated_by}")

    _enqueue_reindex(domain_id)
    return config


def _enqueue_reindex(domain_id: UUID) -> None:
    # Imported lazily to avoid a chunking<->tasks import cycle, same
    # rationale as ontology/service.py's _enqueue_reextraction.
    from src.tasks.pipeline import reindex_domain_chunks_task
    reindex_domain_chunks_task.delay(str(domain_id))


def list_chunks(db: Session, domain_id: UUID, document_id: UUID) -> list[Chunk]:
    # Reuses ingestion's domain-scoped lookup so a document belonging to
    # another domain 404s the same way document detail already does
    # (domain isolation, same pattern as Task 1).
    get_document_or_raise(db, domain_id, document_id)
    return (
        db.query(Chunk)
        .filter(Chunk.document_id == document_id, Chunk.is_active.is_(True))
        .order_by(Chunk.chunk_index)
        .all()
    )


def process_chunk_and_embed(db: Session, document_id: UUID) -> None:
    from . import chunker, embeddings

    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        logging.error(f"process_chunk_and_embed: document {document_id} not found")
        return

    try:
        config = get_or_create_ingestion_config(db, document.domain_id)
        docs = chunker.build_documents(
            document.elements_extracted or [],
            config.paragraphs_per_chunk,
            config.paragraph_overlap,
        )
        if not docs:
            logging.info(f"Document {document_id} produced no chunks (empty text, no tables)")
            document.status = DocumentStatus.READY
            db.commit()
            return

        embedder = embeddings.SentenceTransformerEmbeddings()
        vectors = embedder.embed_documents([d.page_content for d in docs])
        model_version = embeddings.embedding_model_version()

        db.query(Chunk).filter(
            Chunk.document_id == document_id, Chunk.is_active.is_(True)
        ).update({Chunk.is_active: False})

        for index, (doc, vector) in enumerate(zip(docs, vectors)):
            db.add(Chunk(
                id=uuid4(),
                document_id=document_id,
                domain_id=document.domain_id,
                content=doc.page_content,
                content_type=ChunkContentType(doc.metadata["content_type"]),
                chunk_index=index,
                embedding=vector,
                embedding_model_version=model_version,
                is_active=True,
            ))
        document.status = DocumentStatus.READY
        db.commit()
        logging.info(f"Document {document_id} chunked+embedded: {len(docs)} chunks, now ready")
    except Exception as e:
        logging.error(f"Document {document_id} chunk_and_embed failed: {e}")
        db.rollback()
