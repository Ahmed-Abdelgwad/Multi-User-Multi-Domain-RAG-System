from uuid import uuid4
import pytest
from src.entities.domain import Domain
from src.entities.document import Document
from src.entities.chunk import Chunk
from src.entities.enums import DocumentSourceType, DocumentStatus, ChunkContentType
from src.exceptions import InvalidIngestionConfigError, DocumentNotFoundError
from src.chunking import service, models


def _make_domain(db_session) -> Domain:
    domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4())
    db_session.add(domain)
    db_session.commit()
    return domain


def _make_indexing_document(db_session, domain_id, text: str = "", elements: list[dict] | None = None) -> Document:
    # `elements_extracted` is what process_chunk_and_embed actually reads
    # (see ingestion/extraction.py's DocumentElement); `text` is a
    # convenience for the common single-text-block case and still lands
    # on `extracted_text` too (display/metadata only, unused by chunking).
    if elements is None:
        elements = [{"kind": "text", "content": text}] if text else []
    document = Document(
        id=uuid4(),
        domain_id=domain_id,
        source_type=DocumentSourceType.PDF,
        filename="report.pdf",
        storage_key="k",
        status=DocumentStatus.INDEXING,  # the real pre-state: text extraction just finished
        uploaded_by=uuid4(),
        extracted_text=text,
        elements_extracted=elements or None,
    )
    db_session.add(document)
    db_session.commit()
    return document


def _stub_reindex(monkeypatch):
    """Unit tests only exercise the chunking service, not Celery -- stub
    the enqueue call so it never tries to reach a real broker.
    """
    calls = []
    monkeypatch.setattr(service, "_enqueue_reindex", lambda domain_id: calls.append(domain_id))
    return calls


def _stub_embeddings(monkeypatch, dim: int = 4):
    from src.chunking import embeddings as embeddings_module

    monkeypatch.setattr(
        embeddings_module, "embed_texts", lambda texts: [[0.1] * dim for _ in texts]
    )
    monkeypatch.setattr(embeddings_module, "embedding_model_version", lambda: "test-model-v1")


def test_get_or_create_ingestion_config_creates_defaults(db_session):
    domain = _make_domain(db_session)

    config = service.get_or_create_ingestion_config(db_session, domain.id)

    assert config.domain_id == domain.id
    assert config.paragraphs_per_chunk == 2
    assert config.paragraph_overlap == 1


def test_get_or_create_ingestion_config_is_idempotent(db_session):
    domain = _make_domain(db_session)

    first = service.get_or_create_ingestion_config(db_session, domain.id)
    second = service.get_or_create_ingestion_config(db_session, domain.id)

    assert first.id == second.id


def test_update_ingestion_config_persists_new_values(db_session, monkeypatch):
    _stub_reindex(monkeypatch)
    domain = _make_domain(db_session)
    updated_by = uuid4()

    config = service.update_ingestion_config(
        db_session, domain.id, models.DomainIngestionConfigUpdate(paragraphs_per_chunk=3, paragraph_overlap=1), updated_by
    )

    assert config.paragraphs_per_chunk == 3
    assert config.paragraph_overlap == 1
    assert config.updated_by == updated_by


def test_update_ingestion_config_enqueues_reindex(db_session, monkeypatch):
    # Spec 2.4: a chunking config change must trigger re-indexing (was
    # missing entirely -- router.py's entity-centric threshold was the
    # only other "configurable per domain" gap; this closes the one for
    # chunking, mirroring ontology/service.py's schema-change trigger).
    calls = _stub_reindex(monkeypatch)
    domain = _make_domain(db_session)

    service.update_ingestion_config(
        db_session, domain.id, models.DomainIngestionConfigUpdate(paragraphs_per_chunk=3, paragraph_overlap=1), uuid4()
    )

    assert calls == [domain.id]


def test_update_ingestion_config_rejects_overlap_not_smaller_than_group_size(db_session, monkeypatch):
    _stub_reindex(monkeypatch)
    domain = _make_domain(db_session)

    with pytest.raises(InvalidIngestionConfigError):
        service.update_ingestion_config(
            db_session, domain.id, models.DomainIngestionConfigUpdate(paragraphs_per_chunk=2, paragraph_overlap=2), uuid4()
        )


def test_process_chunk_and_embed_creates_active_chunks(db_session, monkeypatch):
    _stub_embeddings(monkeypatch)
    domain = _make_domain(db_session)
    document = _make_indexing_document(db_session, domain.id, "Para one.\n\nPara two.\n\nPara three.")

    service.process_chunk_and_embed(db_session, document.id)

    chunks = db_session.query(Chunk).filter(Chunk.document_id == document.id).all()
    assert len(chunks) == 2  # G=2/O=1 default over 3 paragraphs: [p0,p1], [p1,p2]
    assert all(c.is_active for c in chunks)
    assert all(c.content_type == ChunkContentType.TEXT for c in chunks)
    assert all(c.embedding_model_version == "test-model-v1" for c in chunks)
    assert [c.chunk_index for c in chunks] == [0, 1]
    db_session.refresh(document)
    assert document.status == DocumentStatus.READY  # only now -- not at text-extraction time


def test_process_chunk_and_embed_includes_table_chunks(db_session, monkeypatch):
    _stub_embeddings(monkeypatch)
    domain = _make_domain(db_session)
    table_markdown = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    document = _make_indexing_document(
        db_session, domain.id,
        elements=[
            {"kind": "text", "content": "Para one."},
            {"kind": "table", "content": table_markdown},
        ],
    )

    service.process_chunk_and_embed(db_session, document.id)

    chunks = db_session.query(Chunk).filter(Chunk.document_id == document.id).order_by(Chunk.chunk_index).all()
    assert [c.content_type for c in chunks] == [ChunkContentType.TEXT, ChunkContentType.TABLE]
    assert chunks[1].content == table_markdown


def test_process_chunk_and_embed_respects_element_order_around_a_table(db_session, monkeypatch):
    # Regression test for the real ordering fix: a table now lands
    # between the text that actually surrounded it (per
    # `Document.elements_extracted`'s true reading order), not always
    # after every text chunk.
    _stub_embeddings(monkeypatch)
    domain = _make_domain(db_session)
    table_markdown = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    document = _make_indexing_document(
        db_session, domain.id,
        elements=[
            {"kind": "text", "content": "Before the table."},
            {"kind": "table", "content": table_markdown},
            {"kind": "text", "content": "After the table."},
        ],
    )

    service.process_chunk_and_embed(db_session, document.id)

    chunks = db_session.query(Chunk).filter(Chunk.document_id == document.id).order_by(Chunk.chunk_index).all()
    assert [c.content_type for c in chunks] == [ChunkContentType.TEXT, ChunkContentType.TABLE, ChunkContentType.TEXT]
    assert chunks[0].content == "Before the table."
    assert chunks[2].content == "After the table."


def test_process_chunk_and_embed_reindex_retires_previous_generation(db_session, monkeypatch):
    _stub_embeddings(monkeypatch)
    domain = _make_domain(db_session)
    document = _make_indexing_document(db_session, domain.id, "Para one.\n\nPara two.")

    service.process_chunk_and_embed(db_session, document.id)
    first_generation_ids = {c.id for c in db_session.query(Chunk).filter(Chunk.document_id == document.id)}

    # Re-run (e.g. after a config change) -- old generation must be
    # retired, not deleted (spec 2.4's versioning requirement).
    service.process_chunk_and_embed(db_session, document.id)

    all_chunks = db_session.query(Chunk).filter(Chunk.document_id == document.id).all()
    assert len(all_chunks) == 2 * len(first_generation_ids)
    for c in all_chunks:
        if c.id in first_generation_ids:
            assert c.is_active is False
        else:
            assert c.is_active is True


def test_process_chunk_and_embed_missing_document_is_a_noop(db_session, monkeypatch):
    _stub_embeddings(monkeypatch)
    # Should not raise.
    service.process_chunk_and_embed(db_session, uuid4())


def test_process_chunk_and_embed_empty_text_creates_no_chunks(db_session, monkeypatch):
    _stub_embeddings(monkeypatch)
    domain = _make_domain(db_session)
    document = _make_indexing_document(db_session, domain.id, "")

    service.process_chunk_and_embed(db_session, document.id)

    assert db_session.query(Chunk).filter(Chunk.document_id == document.id).count() == 0
    db_session.refresh(document)
    assert document.status == DocumentStatus.READY  # empty doc is still a terminal, valid state


def test_process_chunk_and_embed_failure_leaves_document_indexing_not_ready(db_session, monkeypatch):
    # Regression test for the status-race this split was introduced to
    # fix: a chunking/embedding failure must not advance the document
    # past INDEXING -- and, just as importantly, must not silently look
    # like a still-in-flight "ready" the way the old single-status design
    # would have (that state never distinguished "not chunked yet" from
    # "chunking failed").
    domain = _make_domain(db_session)
    document = _make_indexing_document(db_session, domain.id, "Para one.\n\nPara two.")

    from src.chunking import embeddings as embeddings_module
    def _boom(texts):
        raise RuntimeError("embedding model unavailable")
    monkeypatch.setattr(embeddings_module, "embed_texts", _boom)

    service.process_chunk_and_embed(db_session, document.id)  # must not raise

    db_session.refresh(document)
    assert document.status == DocumentStatus.INDEXING
    assert db_session.query(Chunk).filter(Chunk.document_id == document.id).count() == 0


def test_list_chunks_scoped_to_domain_and_only_active(db_session, monkeypatch):
    _stub_embeddings(monkeypatch)
    domain_a = _make_domain(db_session)
    domain_b = _make_domain(db_session)
    document = _make_indexing_document(db_session, domain_a.id, "Para one.\n\nPara two.")
    service.process_chunk_and_embed(db_session, document.id)
    service.process_chunk_and_embed(db_session, document.id)  # retires first generation

    chunks = service.list_chunks(db_session, domain_a.id, document.id)
    assert len(chunks) > 0
    assert all(c.is_active for c in chunks)

    with pytest.raises(DocumentNotFoundError):
        service.list_chunks(db_session, domain_b.id, document.id)
