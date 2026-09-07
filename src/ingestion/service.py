import logging
from pathlib import PurePosixPath
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from src.entities.document import Document
from src.entities.enums import DocumentSourceType, DocumentStatus
from src.exceptions import DocumentNotFoundError, UnsupportedDocumentTypeError
from src.storage.core import upload_bytes, download_bytes

# Phase 2 (spec 2.1) only handles PDF/DOCX. CSV/XLSX are accepted by the
# entity/enum already (DocumentSourceType) but wired up in phase 4 (spec
# 2.2) -- kept out of this map until that extraction path exists, so an
# upload fails fast instead of sitting in `pending` forever.
_EXTENSION_TO_SOURCE_TYPE: dict[str, DocumentSourceType] = {
    ".pdf": DocumentSourceType.PDF,
    ".docx": DocumentSourceType.DOCX,
}


def _resolve_source_type(filename: str) -> DocumentSourceType:
    suffix = PurePosixPath(filename).suffix.lower()
    source_type = _EXTENSION_TO_SOURCE_TYPE.get(suffix)
    if source_type is None:
        raise UnsupportedDocumentTypeError(filename)
    return source_type


def get_document_or_raise(db: Session, domain_id: UUID, document_id: UUID) -> Document:
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.domain_id == domain_id)
        .first()
    )
    if not document:
        raise DocumentNotFoundError(document_id)
    return document


def list_documents(db: Session, domain_id: UUID) -> list[Document]:
    return (
        db.query(Document)
        .filter(Document.domain_id == domain_id)
        .order_by(Document.uploaded_at.desc())
        .all()
    )


def create_document(
    db: Session,
    domain_id: UUID,
    uploaded_by: UUID,
    filename: str,
    content_type: str | None,
    raw_bytes: bytes,
) -> Document:
    """Validates the file type, stores the raw bytes in MinIO, inserts the
    `pending` Document row, then enqueues the async extraction task (spec
    2.1's "async pipeline with status tracking"). Upload happens before
    the DB insert so a storage failure never leaves a DB row pointing at
    nothing; the inverse case (DB commit fails after a successful upload)
    is an accepted MVP tradeoff -- no distributed transaction across
    Postgres and MinIO.
    """
    source_type = _resolve_source_type(filename)
    storage_key = f"{domain_id}/{uuid4()}/{filename}"

    upload_bytes(storage_key, raw_bytes, content_type=content_type or "application/octet-stream")

    document = Document(
        id=uuid4(),
        domain_id=domain_id,
        source_type=source_type,
        filename=filename,
        content_type=content_type,
        storage_key=storage_key,
        status=DocumentStatus.PENDING,
        uploaded_by=uploaded_by,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    logging.info(f"Document '{filename}' uploaded to domain {domain_id} by {uploaded_by}")

    _enqueue_extraction(document.id)
    return document


def _enqueue_extraction(document_id: UUID) -> None:
    # Imported lazily to avoid a service<->tasks import cycle (pipeline.py
    # imports this module's process_document_text_extraction).
    from src.tasks.pipeline import extract_text_task
    extract_text_task.delay(str(document_id))


def process_document_text_extraction(db: Session, document_id: UUID) -> None:
    """Runs inside the Celery worker (see tasks/pipeline.py). Owns the
    full pending->processing->ready|failed transition for one document.
    """
    from . import extraction

    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        logging.error(f"process_document_text_extraction: document {document_id} not found")
        return

    try:
        document.status = DocumentStatus.PROCESSING
        db.commit()

        raw_bytes = download_bytes(document.storage_key)
        result = extraction.extract(document.source_type, raw_bytes)

        document.status = DocumentStatus.READY
        document.extracted_text = result.text
        document.ocr_used = result.ocr_used
        document.author = result.author
        document.doc_created_at = result.doc_created_at
        document.tables_extracted = [
            {"page": t.page, "markdown": t.markdown} for t in result.tables
        ] or None
        document.error_message = None
        db.commit()
        logging.info(
            f"Document {document_id} ready ({len(result.text)} chars, "
            f"ocr_used={result.ocr_used}, tables={len(result.tables)})"
        )
    except Exception as e:
        # Covers failure at *any* point above -- including the initial
        # status-transition commit itself -- so a document never gets
        # stuck in pending/processing forever; it always lands on a
        # terminal status (spec 2.1's "async pipeline with status
        # tracking" implies every document eventually resolves).
        logging.error(f"Document {document_id} extraction failed: {e}")
        db.rollback()
        document.status = DocumentStatus.FAILED
        document.error_message = str(e)
        db.commit()
