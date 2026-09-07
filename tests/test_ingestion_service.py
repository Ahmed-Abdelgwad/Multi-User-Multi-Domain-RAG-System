from uuid import uuid4
import pytest
from src.entities.domain import Domain
from src.entities.enums import DocumentSourceType, DocumentStatus
from src.exceptions import UnsupportedDocumentTypeError, DocumentNotFoundError
from src.ingestion import service
from src.ingestion.extraction import ExtractionResult


def _make_domain(db_session) -> Domain:
    domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4())
    db_session.add(domain)
    db_session.commit()
    return domain


def test_create_document_rejects_unsupported_extension(db_session):
    domain = _make_domain(db_session)
    with pytest.raises(UnsupportedDocumentTypeError):
        service.create_document(db_session, domain.id, uuid4(), "data.csv", "text/csv", b"a,b\n1,2")


def test_create_document_uploads_and_enqueues(db_session, monkeypatch):
    domain = _make_domain(db_session)
    uploaded_calls = []
    enqueued_calls = []
    monkeypatch.setattr(service, "upload_bytes", lambda key, data, content_type=None: uploaded_calls.append((key, data, content_type)))
    monkeypatch.setattr(service, "_enqueue_extraction", lambda document_id: enqueued_calls.append(document_id))

    document = service.create_document(db_session, domain.id, uuid4(), "report.pdf", "application/pdf", b"%PDF-1.4 fake")

    assert document.status == DocumentStatus.PENDING
    assert document.source_type == DocumentSourceType.PDF
    assert document.domain_id == domain.id
    assert len(uploaded_calls) == 1
    assert uploaded_calls[0][0] == document.storage_key
    assert enqueued_calls == [document.id]


def test_get_document_or_raise_scopes_by_domain(db_session, monkeypatch):
    domain_a = _make_domain(db_session)
    domain_b = _make_domain(db_session)
    monkeypatch.setattr(service, "upload_bytes", lambda *a, **k: None)
    monkeypatch.setattr(service, "_enqueue_extraction", lambda document_id: None)
    document = service.create_document(db_session, domain_a.id, uuid4(), "report.pdf", "application/pdf", b"x")

    # Right domain: found.
    assert service.get_document_or_raise(db_session, domain_a.id, document.id).id == document.id

    # Same document id, wrong domain: not found (domain isolation).
    with pytest.raises(DocumentNotFoundError):
        service.get_document_or_raise(db_session, domain_b.id, document.id)


def test_list_documents_scoped_to_domain(db_session, monkeypatch):
    domain_a = _make_domain(db_session)
    domain_b = _make_domain(db_session)
    monkeypatch.setattr(service, "upload_bytes", lambda *a, **k: None)
    monkeypatch.setattr(service, "_enqueue_extraction", lambda document_id: None)
    service.create_document(db_session, domain_a.id, uuid4(), "a.pdf", "application/pdf", b"x")
    service.create_document(db_session, domain_b.id, uuid4(), "b.pdf", "application/pdf", b"x")

    assert len(service.list_documents(db_session, domain_a.id)) == 1
    assert len(service.list_documents(db_session, domain_b.id)) == 1


def test_process_document_text_extraction_marks_indexing_on_success(db_session, monkeypatch):
    domain = _make_domain(db_session)
    monkeypatch.setattr(service, "upload_bytes", lambda *a, **k: None)
    monkeypatch.setattr(service, "_enqueue_extraction", lambda document_id: None)
    document = service.create_document(db_session, domain.id, uuid4(), "report.pdf", "application/pdf", b"x")

    monkeypatch.setattr(service, "download_bytes", lambda key: b"raw-bytes")
    from src.ingestion import extraction as extraction_module
    monkeypatch.setattr(
        extraction_module,
        "extract",
        lambda source_type, raw: ExtractionResult(text="parsed text", ocr_used=False, author="A. Author", doc_created_at=None),
    )

    service.process_document_text_extraction(db_session, document.id)

    db_session.refresh(document)
    # Not READY yet -- that only happens once chunk_and_embed_task (chained
    # separately) finishes. See DocumentStatus's docstring for why this
    # was split into two statuses.
    assert document.status == DocumentStatus.INDEXING
    assert document.extracted_text == "parsed text"
    assert document.author == "A. Author"
    assert document.error_message is None


def test_process_document_text_extraction_marks_failed_on_error(db_session, monkeypatch):
    domain = _make_domain(db_session)
    monkeypatch.setattr(service, "upload_bytes", lambda *a, **k: None)
    monkeypatch.setattr(service, "_enqueue_extraction", lambda document_id: None)
    document = service.create_document(db_session, domain.id, uuid4(), "report.pdf", "application/pdf", b"x")

    def _boom(key):
        raise RuntimeError("minio is down")
    monkeypatch.setattr(service, "download_bytes", _boom)

    service.process_document_text_extraction(db_session, document.id)

    db_session.refresh(document)
    assert document.status == DocumentStatus.FAILED
    assert "minio is down" in document.error_message
