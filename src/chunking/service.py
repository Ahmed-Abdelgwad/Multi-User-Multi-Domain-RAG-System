import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from src.entities.chunk import Chunk
from src.entities.document import Document
from src.entities.domain_ingestion_config import DomainIngestionConfig
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
    return config


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
    """Runs inside the Celery worker (see tasks/pipeline.py), auto-chained
    after `extract_text_task` succeeds. Paragraph-groups the document's
    body text (PGC) + folds in any extracted tables as atomic chunks,
    embeds them, and writes them as the new active generation -- the
    previous generation (if any, e.g. a re-chunk after a config change)
    is retired via `is_active=False` rather than deleted (spec 2.4's
    versioning requirement).

    Failure here is isolated from `Document.status`: text extraction
    already succeeded (that's what triggered this task), so a
    chunking/embedding failure is logged and left for a retry/re-index
    rather than flipping an already-`ready` document back to `failed`.
    """
    from . import chunker, embeddings

    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        logging.error(f"process_chunk_and_embed: document {document_id} not found")
        return

    try:
        config = get_or_create_ingestion_config(db, document.domain_id)
        candidates = chunker.build_chunks(
            document.extracted_text or "",
            document.tables_extracted,
            config.paragraphs_per_chunk,
            config.paragraph_overlap,
        )
        if not candidates:
            logging.info(f"Document {document_id} produced no chunks (empty text, no tables)")
            return

        vectors = embeddings.embed_texts([c.content for c in candidates])
        model_version = embeddings.embedding_model_version()

        db.query(Chunk).filter(
            Chunk.document_id == document_id, Chunk.is_active.is_(True)
        ).update({Chunk.is_active: False})

        for index, (candidate, vector) in enumerate(zip(candidates, vectors)):
            db.add(Chunk(
                id=uuid4(),
                document_id=document_id,
                domain_id=document.domain_id,
                content=candidate.content,
                content_type=candidate.content_type,
                chunk_index=index,
                embedding=vector,
                embedding_model_version=model_version,
                is_active=True,
            ))
        db.commit()
        logging.info(f"Document {document_id} chunked+embedded: {len(candidates)} chunks")
    except Exception as e:
        logging.error(f"Document {document_id} chunk_and_embed failed: {e}")
        db.rollback()
