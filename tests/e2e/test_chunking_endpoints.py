from io import BytesIO
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from src.entities.enums import DomainRole
from src.ingestion import service as ingestion_service
from src.chunking import service as chunking_service, embeddings as embeddings_module


@pytest.fixture(autouse=True)
def _stub_storage_pipeline_and_embeddings(monkeypatch):
    """e2e tests exercise the HTTP layer + DB only -- MinIO/Celery/the real
    embedding model aren't available under plain `pytest`, same rationale
    as the existing ingestion e2e tests. The real integration (including a
    real model load) is proven separately by the live docker-compose
    smoke test.
    """
    monkeypatch.setattr(ingestion_service, "upload_bytes", lambda *a, **k: None)
    monkeypatch.setattr(ingestion_service, "_enqueue_extraction", lambda document_id: None)
    monkeypatch.setattr(embeddings_module, "embed_texts", lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts])
    monkeypatch.setattr(embeddings_module, "embedding_model_version", lambda: "test-model-v1")


def _create_domain(client: TestClient, headers, name=None):
    return client.post("/domains/", headers=headers, json={"name": name or f"domain-{uuid4()}", "description": "t"})


def _upload(client: TestClient, headers, domain_id, filename="report.pdf"):
    return client.post(
        f"/domains/{domain_id}/documents/",
        headers=headers,
        files={"file": (filename, BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )


# --- ingestion-config endpoints ---

def test_domain_admin_can_get_default_ingestion_config(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="cfg-domain").json()["id"]

    response = client.get(f"/domains/{domain_id}/ingestion-config/", headers=platform_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["paragraphs_per_chunk"] == 2
    assert body["paragraph_overlap"] == 1


def test_domain_admin_can_update_ingestion_config(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="cfg-domain-update").json()["id"]

    response = client.put(
        f"/domains/{domain_id}/ingestion-config/",
        headers=platform_admin_headers,
        json={"paragraphs_per_chunk": 3, "paragraph_overlap": 1},
    )

    assert response.status_code == 200
    assert response.json()["paragraphs_per_chunk"] == 3


def test_update_ingestion_config_rejects_invalid_overlap(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="cfg-domain-invalid").json()["id"]

    response = client.put(
        f"/domains/{domain_id}/ingestion-config/",
        headers=platform_admin_headers,
        json={"paragraphs_per_chunk": 2, "paragraph_overlap": 2},
    )

    assert response.status_code == 400


def test_contributor_cannot_update_ingestion_config(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="cfg-domain-rbac").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.put(
        f"/domains/{domain_id}/ingestion-config/",
        headers=contributor_headers,
        json={"paragraphs_per_chunk": 3, "paragraph_overlap": 1},
    )

    assert response.status_code == 403


# --- chunks listing endpoint ---

def test_reader_can_list_chunks_after_processing(client: TestClient, platform_admin_headers, make_user_with_role, db_session, monkeypatch):
    domain_id = _create_domain(client, platform_admin_headers, name="chunks-domain").json()["id"]
    reader_headers, _ = make_user_with_role(domain_id, DomainRole.READER)
    document_id = _upload(client, platform_admin_headers, domain_id).json()["id"]

    # Run the pipeline stages synchronously (Celery isn't running under
    # plain pytest) against the same session the API uses, so there's
    # real extracted_text/chunks to list. Storage download + text
    # extraction are stubbed for the same reason as `_enqueue_extraction`
    # above -- MinIO isn't running here either.
    from src.ingestion import extraction as extraction_module
    from src.ingestion.extraction import ExtractionResult

    monkeypatch.setattr(ingestion_service, "download_bytes", lambda key: b"raw-bytes")
    monkeypatch.setattr(
        extraction_module,
        "extract",
        lambda source_type, raw: ExtractionResult(
            text="Para one.\n\nPara two.\n\nPara three.", ocr_used=False, author=None, doc_created_at=None
        ),
    )

    from uuid import UUID
    ingestion_service.process_document_text_extraction(db_session, UUID(document_id))
    chunking_service.process_chunk_and_embed(db_session, UUID(document_id))

    response = client.get(f"/domains/{domain_id}/documents/{document_id}/chunks/", headers=reader_headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2  # G=2/O=1 default over 3 paragraphs
    assert all(chunk["is_active"] for chunk in body)


def test_chunks_endpoint_404s_for_document_in_another_domain(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_a = _create_domain(client, platform_admin_headers, name="chunks-domain-a").json()["id"]
    domain_b = _create_domain(client, platform_admin_headers, name="chunks-domain-b").json()["id"]
    admin_b_headers, _ = make_user_with_role(domain_b, DomainRole.ADMIN)
    document_id = _upload(client, platform_admin_headers, domain_a).json()["id"]

    response = client.get(f"/domains/{domain_b}/documents/{document_id}/chunks/", headers=admin_b_headers)

    assert response.status_code == 404


def test_user_without_role_cannot_list_chunks(client: TestClient, platform_admin_headers, auth_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="chunks-domain-norole").json()["id"]
    document_id = _upload(client, platform_admin_headers, domain_id).json()["id"]

    response = client.get(f"/domains/{domain_id}/documents/{document_id}/chunks/", headers=auth_headers)

    assert response.status_code == 403
