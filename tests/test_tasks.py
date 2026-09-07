from uuid import uuid4
from src.tasks.celery_app import celery_app
from src.tasks.pipeline import (
    ping, extract_text_task, chunk_and_embed_task, reextract_domain_task, batch_extract_entities_task,
)


def test_ping_task_runs_synchronously_and_returns_pong():
    """Runs the task inline (no broker/worker needed) to prove the Celery
    app + task registration wiring is correct. The real broker/worker
    round-trip is verified separately via the docker-compose smoke test.
    """
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        result = ping.delay()
        assert result.get(timeout=5) == "pong"
    finally:
        celery_app.conf.task_always_eager = False


def _make_pending_document(db_session):
    from src.entities.domain import Domain
    from src.entities.document import Document
    from src.entities.enums import DocumentSourceType, DocumentStatus

    domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4())
    db_session.add(domain)
    document = Document(
        id=uuid4(), domain_id=domain.id, source_type=DocumentSourceType.PDF,
        filename="r.pdf", storage_key="k", status=DocumentStatus.PENDING, uploaded_by=uuid4(),
    )
    db_session.add(document)
    db_session.commit()
    return document


def test_extract_text_task_chains_into_chunk_and_embed_on_indexing(db_session, monkeypatch):
    """Spec 2.4's auto-chaining: once a document lands on `indexing`
    (text extracted, not yet chunked -- see DocumentStatus's docstring),
    extract_text_task must enqueue chunk_and_embed_task itself -- no
    manual trigger needed for the pipeline to continue. The task opens
    its own session via `SessionLocal()`; patched here to hand back the
    same SQLite test session so the task's writes are visible to the
    assertions below.
    """
    import src.database.core as database_core
    from src.ingestion import service as ingestion_service
    from src.ingestion import extraction as extraction_module
    from src.ingestion.extraction import ExtractionResult

    monkeypatch.setattr(database_core, "SessionLocal", lambda: db_session)
    document = _make_pending_document(db_session)

    monkeypatch.setattr(ingestion_service, "download_bytes", lambda key: b"raw")
    monkeypatch.setattr(
        extraction_module, "extract",
        lambda source_type, raw: ExtractionResult(text="Para one.", ocr_used=False, author=None, doc_created_at=None),
    )

    chained_calls = []
    monkeypatch.setattr(chunk_and_embed_task, "delay", lambda document_id: chained_calls.append(document_id))

    extract_text_task(str(document.id))

    assert chained_calls == [str(document.id)]


def test_extract_text_task_does_not_chain_when_extraction_fails(db_session, monkeypatch):
    import src.database.core as database_core
    from src.ingestion import service as ingestion_service

    monkeypatch.setattr(database_core, "SessionLocal", lambda: db_session)
    document = _make_pending_document(db_session)

    def _boom(key):
        raise RuntimeError("minio is down")
    monkeypatch.setattr(ingestion_service, "download_bytes", _boom)

    chained_calls = []
    monkeypatch.setattr(chunk_and_embed_task, "delay", lambda document_id: chained_calls.append(document_id))

    extract_text_task(str(document.id))

    assert chained_calls == []


def _make_chunk(db_session, document, content="Alice works at Acme.", is_active=True, entities_extracted_at=None):
    from src.entities.chunk import Chunk
    from src.entities.enums import ChunkContentType

    chunk = Chunk(
        id=uuid4(), document_id=document.id, domain_id=document.domain_id,
        content=content, content_type=ChunkContentType.TEXT, chunk_index=0,
        is_active=is_active, entities_extracted_at=entities_extracted_at,
    )
    db_session.add(chunk)
    db_session.commit()
    return chunk


def test_reextract_domain_task_resets_active_chunks_only(db_session, monkeypatch):
    """Spec 2.6's re-extraction trigger: activating a new ontology version
    must reset already-extracted *active* chunks back to
    `entities_extracted_at=NULL` so the next batch tick re-processes them
    -- a retired (`is_active=False`) chunk from an old chunking generation
    is left alone, it's not part of the current document anymore.
    """
    import src.database.core as database_core
    from src.entities.domain import Domain
    from src.entities.document import Document
    from src.entities.enums import DocumentSourceType, DocumentStatus
    from datetime import datetime, timezone

    monkeypatch.setattr(database_core, "SessionLocal", lambda: db_session)
    domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4())
    db_session.add(domain)
    document = Document(
        id=uuid4(), domain_id=domain.id, source_type=DocumentSourceType.PDF,
        filename="ready.pdf", storage_key="k1", status=DocumentStatus.READY, uploaded_by=uuid4(),
    )
    db_session.add(document)
    db_session.commit()

    already_extracted = datetime.now(timezone.utc)
    active_chunk = _make_chunk(db_session, document, entities_extracted_at=already_extracted)
    retired_chunk = _make_chunk(db_session, document, is_active=False, entities_extracted_at=already_extracted)
    domain_id, active_chunk_id, retired_chunk_id = domain.id, active_chunk.id, retired_chunk.id

    reextract_domain_task(str(domain_id))

    # `reextract_domain_task` commits+closes the same session (SessionLocal
    # is patched to hand back this exact `db_session`), which expires and
    # detaches every object it was tracking -- so state is checked here via
    # fresh queries (by the ids captured above) rather than `.refresh()` on
    # the now-detached `active_chunk`/`retired_chunk` instances.
    from src.entities.chunk import Chunk
    assert db_session.query(Chunk).filter(Chunk.id == active_chunk_id).one().entities_extracted_at is None
    assert db_session.query(Chunk).filter(Chunk.id == retired_chunk_id).one().entities_extracted_at is not None


def test_batch_extract_entities_task_processes_only_unextracted_documents(db_session, monkeypatch):
    """Spec 2.5's periodic sweep: a document with an active,
    not-yet-extracted chunk gets processed exactly once per tick; a
    document whose chunks are all already extracted is left alone.
    """
    import src.database.core as database_core
    from src.entities.domain import Domain
    from src.entities.document import Document
    from src.entities.enums import DocumentSourceType, DocumentStatus
    from datetime import datetime, timezone

    monkeypatch.setattr(database_core, "SessionLocal", lambda: db_session)
    domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4())
    db_session.add(domain)
    pending_document = Document(
        id=uuid4(), domain_id=domain.id, source_type=DocumentSourceType.PDF,
        filename="pending.pdf", storage_key="k1", status=DocumentStatus.READY, uploaded_by=uuid4(),
    )
    done_document = Document(
        id=uuid4(), domain_id=domain.id, source_type=DocumentSourceType.PDF,
        filename="done.pdf", storage_key="k2", status=DocumentStatus.READY, uploaded_by=uuid4(),
    )
    db_session.add_all([pending_document, done_document])
    db_session.commit()

    _make_chunk(db_session, pending_document, entities_extracted_at=None)
    _make_chunk(db_session, done_document, entities_extracted_at=datetime.now(timezone.utc))
    pending_document_id = pending_document.id  # captured before the task's commit/close expires+detaches it

    # process_extract_entities_for_document is imported inside the task
    # body (`from src.extraction.service import ...`), so patching it at
    # its source is picked up when that import statement executes.
    processed = []
    import src.extraction.service as extraction_service
    monkeypatch.setattr(
        extraction_service, "process_extract_entities_for_document", lambda db, document_id: processed.append(document_id)
    )

    batch_extract_entities_task()

    assert processed == [pending_document_id]
