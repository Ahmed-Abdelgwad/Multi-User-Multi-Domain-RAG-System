from uuid import uuid4
from src.tasks.celery_app import celery_app
from src.tasks.pipeline import (
    ping, extract_text_task, chunk_and_embed_task, reextract_domain_task, batch_extract_entities_task,
    reindex_domain_chunks_task, evaluate_query_log_task,
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


def test_reindex_domain_chunks_task_fans_out_to_ready_documents_only(db_session, monkeypatch):
    """Spec 2.4's re-indexing trigger, mirroring reextract_domain_task's
    shape: fans out to chunk_and_embed_task for every `ready` document in
    the domain (each run retires its previous chunk generation and
    re-chunks with the domain's current config, see
    chunking/service.py::process_chunk_and_embed) -- a still-processing
    document and a document in a different domain are left alone.
    """
    import src.database.core as database_core
    from src.entities.domain import Domain
    from src.entities.document import Document
    from src.entities.enums import DocumentSourceType, DocumentStatus

    monkeypatch.setattr(database_core, "SessionLocal", lambda: db_session)
    domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4())
    other_domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4())
    db_session.add_all([domain, other_domain])

    ready_document = Document(
        id=uuid4(), domain_id=domain.id, source_type=DocumentSourceType.PDF,
        filename="ready.pdf", storage_key="k1", status=DocumentStatus.READY, uploaded_by=uuid4(),
    )
    processing_document = Document(
        id=uuid4(), domain_id=domain.id, source_type=DocumentSourceType.PDF,
        filename="processing.pdf", storage_key="k2", status=DocumentStatus.PROCESSING, uploaded_by=uuid4(),
    )
    other_domain_ready_document = Document(
        id=uuid4(), domain_id=other_domain.id, source_type=DocumentSourceType.PDF,
        filename="other.pdf", storage_key="k3", status=DocumentStatus.READY, uploaded_by=uuid4(),
    )
    db_session.add_all([ready_document, processing_document, other_domain_ready_document])
    db_session.commit()
    domain_id, ready_document_id = domain.id, ready_document.id  # captured before the task detaches them

    fanned_out = []
    monkeypatch.setattr(chunk_and_embed_task, "delay", lambda document_id: fanned_out.append(document_id))

    reindex_domain_chunks_task(str(domain_id))

    assert fanned_out == [str(ready_document_id)]


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


def test_evaluate_query_log_task_creates_pending_row_before_delegating(db_session, monkeypatch):
    """Spec 4.1/4.3: the task's own responsibility is just to guarantee an
    EvaluationResult row exists at PENDING before the real judge call
    (evaluation/service.py::evaluate_query_log) runs -- so a client
    polling mid-evaluation always finds a real row, never "not found."
    """
    import src.database.core as database_core
    from src.entities.query_log import QueryLog
    from src.entities.evaluation_result import EvaluationResult
    from src.entities.enums import LLMRoute, EvaluationStatus

    monkeypatch.setattr(database_core, "SessionLocal", lambda: db_session)

    query_log = QueryLog(
        id=uuid4(), user_id=uuid4(), domain_ids=[str(uuid4())], query="q", answer="a",
        route=LLMRoute.API, confidence=0.9, sources=[], graph_context=[],
    )
    db_session.add(query_log)
    db_session.commit()

    status_seen_at_call_time = {}
    import src.evaluation.service as evaluation_service

    def _fake_evaluate_query_log(db, query_log_id):
        row = db.query(EvaluationResult).filter(EvaluationResult.query_log_id == query_log_id).first()
        status_seen_at_call_time["status"] = row.status
        row.status = EvaluationStatus.COMPLETED
        db.commit()
        return row

    monkeypatch.setattr(evaluation_service, "evaluate_query_log", _fake_evaluate_query_log)

    query_log_id = query_log.id  # captured before the task's commit/close expires+detaches it
    evaluate_query_log_task(str(query_log_id))

    assert status_seen_at_call_time["status"] == EvaluationStatus.PENDING
    row = db_session.query(EvaluationResult).filter(EvaluationResult.query_log_id == query_log_id).first()
    assert row.status == EvaluationStatus.COMPLETED


def test_evaluate_query_log_task_does_not_duplicate_row_on_retry(db_session, monkeypatch):
    import src.database.core as database_core
    from src.entities.query_log import QueryLog
    from src.entities.evaluation_result import EvaluationResult
    from src.entities.enums import LLMRoute

    monkeypatch.setattr(database_core, "SessionLocal", lambda: db_session)

    query_log = QueryLog(
        id=uuid4(), user_id=uuid4(), domain_ids=[str(uuid4())], query="q", answer="a",
        route=LLMRoute.API, confidence=0.9, sources=[], graph_context=[],
    )
    db_session.add(query_log)
    db_session.add(EvaluationResult(id=uuid4(), query_log_id=query_log.id))
    db_session.commit()

    import src.evaluation.service as evaluation_service
    monkeypatch.setattr(evaluation_service, "evaluate_query_log", lambda db, query_log_id: None)

    query_log_id = query_log.id  # captured before the task's commit/close expires+detaches it
    evaluate_query_log_task(str(query_log_id))

    rows = db_session.query(EvaluationResult).filter(EvaluationResult.query_log_id == query_log_id).all()
    assert len(rows) == 1
