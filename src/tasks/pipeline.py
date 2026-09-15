"""Ingestion pipeline tasks. Phase 1 defined a smoke-test task to prove
the worker/broker/backend wiring works end-to-end; phase 2 (spec 2.1)
added the text-extraction task; phase 3 (spec 2.4) adds chunking +
embedding, auto-chained after extraction succeeds. Phase 6 (spec 2.6)
adds `reextract_domain_task`, triggered whenever a domain activates a new
ontology version. Phase 7 (spec 2.5) adds `batch_extract_entities_task`,
a periodic (Celery Beat, see celery_app.py's `beat_schedule`) sweep that
does the actual entity/relation extraction -- deliberately *not* chained
directly off `chunk_and_embed_task`, so the knowledge graph lags the
vector index by one job cycle (the plan's canonical 2.5 text explicitly
accepts this for MVP) instead of extraction blocking or racing the
ingest pipeline. `reextract_domain_task` plugs into the same mechanism by
resetting `Chunk.entities_extracted_at` back to NULL rather than running
or enqueuing extraction itself -- the next batch tick picks those chunks
back up naturally, so there's only ever one code path that actually calls
the (heavy, RAM-hungry) extractor.

`reindex_domain_chunks_task` closes spec 2.4's analogous requirement
("chunk versioning supports re-indexing on ... schema change"): a
domain's chunking config (paragraphs_per_chunk/paragraph_overlap)
changing invalidates every chunk `chunk_and_embed_task` already produced
for that domain. Unlike entity extraction there's no separate periodic
sweep to piggyback on -- re-chunking is document-granular already (see
`chunk_and_embed_task`), and `process_chunk_and_embed` is already
idempotent/re-runnable (retires the previous generation, keeps history --
see chunking/service.py), so this task just fans back out to the same
task per `ready` document in the domain instead of introducing a second
sweep mechanism.

`evaluate_query_log_task` (spec section 4, phase 3) is the first task in
this module dispatched from a live user-facing request rather than an
ingestion/config-change side effect: retrieval/service.py::answer_query
fires it immediately after committing a QueryLog row, so the Judge LLM
call never adds to /query's own response latency.
"""
from uuid import UUID
from .celery_app import celery_app


@celery_app.task(name="pipeline.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="pipeline.extract_text", bind=True, max_retries=2, default_retry_delay=10)
def extract_text_task(self, document_id: str) -> None:
    """Runs the async pipeline's first stage (spec 2.1: "async pipeline
    with status tracking") for one Document: downloads the raw file from
    MinIO, extracts text (+OCR fallback, +author/creation-date metadata),
    and updates the Document's status to INDEXING (not READY -- that only
    happens once chunk_and_embed_task itself finishes, see
    chunking/service.py). Opens its own DB session since it runs in the
    worker process, not under a request's `DbSession` dependency. On
    success, chains into `chunk_and_embed_task` (spec 2.4) so upload ->
    extraction -> chunking -> embedding is one continuous async pipeline
    with no manual trigger needed.
    """
    from src.database.core import SessionLocal
    from src.entities.document import Document
    from src.entities.enums import DocumentStatus
    from src.ingestion.service import process_document_text_extraction

    db = SessionLocal()
    try:
        process_document_text_extraction(db, UUID(document_id))
        document = db.query(Document).filter(Document.id == UUID(document_id)).first()
        if document and document.status == DocumentStatus.INDEXING:
            chunk_and_embed_task.delay(document_id)
    finally:
        db.close()


@celery_app.task(name="pipeline.chunk_and_embed", bind=True, max_retries=2, default_retry_delay=10)
def chunk_and_embed_task(self, document_id: str) -> None:
    """Runs the async pipeline's second stage (spec 2.4): Paragraph Group
    Chunking over the document's extracted text/tables, then embeds and
    persists each chunk. Opens its own DB session for the same reason as
    `extract_text_task`.
    """
    from src.database.core import SessionLocal
    from src.chunking.service import process_chunk_and_embed

    db = SessionLocal()
    try:
        process_chunk_and_embed(db, UUID(document_id))
    finally:
        db.close()


@celery_app.task(name="pipeline.reextract_domain", bind=True, max_retries=2, default_retry_delay=10)
def reextract_domain_task(self, domain_id: str) -> None:
    """Fired whenever a domain activates a new ontology version (spec 2.6).
    A schema change invalidates the ontology_version stamp on every
    existing graph_node/graph_edge in the domain, so every active chunk's
    prior extraction is stale. Resets `entities_extracted_at` back to NULL
    on those chunks rather than running (or enqueueing) extraction itself
    here -- the next `batch_extract_entities_task` tick (spec 2.5) picks
    them back up on its own, the same "post-ingest, one job cycle lag"
    shape a freshly-chunked document already goes through.
    """
    from src.database.core import SessionLocal
    from src.entities.chunk import Chunk

    db = SessionLocal()
    try:
        db.query(Chunk).filter(
            Chunk.domain_id == UUID(domain_id), Chunk.is_active.is_(True)
        ).update({Chunk.entities_extracted_at: None})
        db.commit()
    finally:
        db.close()


@celery_app.task(name="pipeline.reindex_domain_chunks", bind=True, max_retries=2, default_retry_delay=10)
def reindex_domain_chunks_task(self, domain_id: str) -> None:
    """Fired whenever a domain's chunking config changes (spec 2.4). Fans
    out to `chunk_and_embed_task` for every `ready` document in the
    domain -- each run re-chunks with the domain's current config and
    retires the previous chunk generation (see
    chunking/service.py::process_chunk_and_embed), the same versioning
    behavior a fresh document already goes through.
    """
    from src.database.core import SessionLocal
    from src.entities.document import Document
    from src.entities.enums import DocumentStatus

    db = SessionLocal()
    try:
        document_ids = [
            row[0] for row in db.query(Document.id)
            .filter(Document.domain_id == UUID(domain_id), Document.status == DocumentStatus.READY)
            .all()
        ]
    finally:
        db.close()

    for document_id in document_ids:
        chunk_and_embed_task.delay(str(document_id))


@celery_app.task(name="pipeline.backfill_neo4j_graph")
def backfill_neo4j_graph_task() -> None:
    """One-off migration task (spec 3.2): replays every already-extracted
    graph_node/graph_edge (from before Neo4j existed) through the same
    upsert_node_to_graph/upsert_edge_to_graph calls the live extraction
    path uses, once per chunk that actually linked to it -- not run
    automatically, triggered manually once after Neo4j is stood up.
    """
    from src.database.core import SessionLocal
    from src.entities.graph_node import GraphNode
    from src.entities.graph_edge import GraphEdge
    from src.entities.chunk_graph_node_link import ChunkGraphNodeLink
    from src.entities.chunk_graph_edge_link import ChunkGraphEdgeLink
    from src.extraction import graph_store

    db = SessionLocal()
    try:
        for node in db.query(GraphNode).all():
            chunk_ids = [
                row[0] for row in
                db.query(ChunkGraphNodeLink.chunk_id).filter(ChunkGraphNodeLink.graph_node_id == node.id).all()
            ]
            for chunk_id in chunk_ids:
                graph_store.upsert_node_to_graph(node, chunk_id)

        for edge in db.query(GraphEdge).all():
            chunk_ids = [
                row[0] for row in
                db.query(ChunkGraphEdgeLink.chunk_id).filter(ChunkGraphEdgeLink.graph_edge_id == edge.id).all()
            ]
            for chunk_id in chunk_ids:
                graph_store.upsert_edge_to_graph(edge, chunk_id)
    finally:
        db.close()


@celery_app.task(name="pipeline.evaluate_query_log", bind=True, max_retries=2, default_retry_delay=10)
def evaluate_query_log_task(self, query_log_id: str) -> None:
    """Spec 4.1's async judge call, fired by retrieval/service.py::answer_query
    right after a QueryLog row is committed -- 4.1's "does not gate the
    user-facing response," the exact same "commit first, .delay() after"
    ordering already used by reindex_domain_chunks_task/reextract_domain_task.
    First creates the EvaluationResult row at PENDING (single commit) if
    one doesn't already exist -- so a retry re-enters an already-PENDING
    row instead of creating a duplicate -- then hands off to
    evaluation/service.py::evaluate_query_log, which does the actual
    judge call and always leaves the row at a terminal status.
    """
    from src.database.core import SessionLocal
    from src.entities.evaluation_result import EvaluationResult
    from src.evaluation.service import evaluate_query_log
    from uuid import uuid4

    db = SessionLocal()
    try:
        existing = db.query(EvaluationResult).filter(EvaluationResult.query_log_id == UUID(query_log_id)).first()
        if existing is None:
            db.add(EvaluationResult(id=uuid4(), query_log_id=UUID(query_log_id)))
            db.commit()

        evaluate_query_log(db, UUID(query_log_id))
    finally:
        db.close()


@celery_app.task(name="pipeline.run_golden_regression_for_domain", bind=True, max_retries=2, default_retry_delay=10)
def run_golden_regression_for_domain_task(self, domain_id: str) -> None:
    """Runs spec 4.5's regression for one domain's golden set -- a real
    retrieval + generation + reference-aware judge call per curated
    item. Fanned out to per-domain (rather than looping over every
    domain in one task) so one domain's failure/slowness is isolated
    from the rest, same fan-out shape as `reindex_domain_chunks_task`.
    Triggered either by the nightly `run_golden_regression_task` sweep
    below, or manually via `POST /domains/{id}/golden-qa/run-regression`.
    """
    from src.database.core import SessionLocal
    from src.evaluation.service import run_golden_regression_for_domain

    db = SessionLocal()
    try:
        run_golden_regression_for_domain(db, UUID(domain_id))
    finally:
        db.close()


@celery_app.task(name="pipeline.run_golden_regression")
def run_golden_regression_task() -> None:
    """Spec 4.5's nightly sweep (Celery Beat, see celery_app.py's
    `beat_schedule` -- a real cron schedule, not a fixed interval):
    finds every domain with at least one `GoldenQAItem` and fans out to
    `run_golden_regression_for_domain_task` per domain.
    """
    from src.database.core import SessionLocal
    from src.entities.golden_qa_item import GoldenQAItem

    db = SessionLocal()
    try:
        domain_ids = [row[0] for row in db.query(GoldenQAItem.domain_id).distinct().all()]
    finally:
        db.close()

    for domain_id in domain_ids:
        run_golden_regression_for_domain_task.delay(str(domain_id))


@celery_app.task(name="pipeline.batch_extract_entities")
def batch_extract_entities_task() -> None:
    """Spec 2.5's "background batch job post-ingest" trigger, run on a
    fixed interval via Celery Beat rather than chained off
    `chunk_and_embed_task` (see this module's docstring for why). Finds
    every document with at least one active, not-yet-extracted chunk
    (`entities_extracted_at IS NULL`) and processes it -- covers both a
    freshly chunked document and one reset by `reextract_domain_task`
    above.
    """
    from src.database.core import SessionLocal
    from src.entities.chunk import Chunk
    from src.extraction.service import process_extract_entities_for_document

    db = SessionLocal()
    try:
        document_ids = [
            row[0] for row in
            db.query(Chunk.document_id)
            .filter(Chunk.is_active.is_(True), Chunk.entities_extracted_at.is_(None))
            .distinct()
            .all()
        ]
        for document_id in document_ids:
            process_extract_entities_for_document(db, document_id)
    finally:
        db.close()
