from io import BytesIO
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from src.entities.enums import DomainRole
from src.ingestion import service as ingestion_service


@pytest.fixture(autouse=True)
def _stub_storage_and_pipeline(monkeypatch):
    """e2e tests exercise the HTTP layer + DB only. MinIO/Celery aren't
    running under plain `pytest` (they're services in docker-compose.yml)
    -- that real integration is proven separately by the live
    docker-compose smoke test, same as Task 1's verification approach.
    """
    monkeypatch.setattr(ingestion_service, "upload_bytes", lambda *a, **k: None)
    monkeypatch.setattr(ingestion_service, "_enqueue_extraction", lambda document_id: None)


def _create_domain(client: TestClient, headers, name=None):
    return client.post(
        "/domains/", headers=headers, json={"name": name or f"domain-{uuid4()}", "description": "t"}
    )


def _upload(client: TestClient, headers, domain_id, filename="report.pdf", content=b"%PDF-1.4 fake", content_type="application/pdf"):
    return client.post(
        f"/domains/{domain_id}/documents/",
        headers=headers,
        files={"file": (filename, BytesIO(content), content_type)},
    )


def test_contributor_can_upload_document(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="docs-domain").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = _upload(client, contributor_headers, domain_id)

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "report.pdf"
    assert body["status"] == "pending"
    assert body["source_type"] == "pdf"


def test_reader_cannot_upload_document(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="docs-domain-reader").json()["id"]
    reader_headers, _ = make_user_with_role(domain_id, DomainRole.READER)

    response = _upload(client, reader_headers, domain_id)

    assert response.status_code == 403


def test_user_without_role_cannot_upload_document(client: TestClient, platform_admin_headers, auth_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="docs-domain-norole").json()["id"]

    response = _upload(client, auth_headers, domain_id)

    assert response.status_code == 403


def test_unsupported_file_type_rejected(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="docs-domain-unsupported").json()["id"]

    response = _upload(
        client, platform_admin_headers, domain_id, filename="data.csv", content=b"a,b\n1,2", content_type="text/csv"
    )

    assert response.status_code == 415


def test_reader_can_list_and_get_documents(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="docs-domain-list").json()["id"]
    reader_headers, _ = make_user_with_role(domain_id, DomainRole.READER)
    uploaded = _upload(client, platform_admin_headers, domain_id).json()

    list_response = client.get(f"/domains/{domain_id}/documents/", headers=reader_headers)
    assert list_response.status_code == 200
    assert any(d["id"] == uploaded["id"] for d in list_response.json())

    get_response = client.get(f"/domains/{domain_id}/documents/{uploaded['id']}", headers=reader_headers)
    assert get_response.status_code == 200
    assert get_response.json()["id"] == uploaded["id"]


def test_document_isolated_from_other_domains(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_a = _create_domain(client, platform_admin_headers, name="docs-domain-a").json()["id"]
    domain_b = _create_domain(client, platform_admin_headers, name="docs-domain-b").json()["id"]
    uploaded = _upload(client, platform_admin_headers, domain_a).json()
    reader_b_headers, _ = make_user_with_role(domain_b, DomainRole.READER)

    # A reader of domain B has no role at all in domain A -> 403 before
    # the document lookup even happens.
    cross_domain_response = client.get(f"/domains/{domain_a}/documents/{uploaded['id']}", headers=reader_b_headers)
    assert cross_domain_response.status_code == 403

    # The same document id doesn't resolve under domain B's own path,
    # even for someone who *does* have a role there (domain isolation).
    wrong_domain_path_response = client.get(f"/domains/{domain_b}/documents/{uploaded['id']}", headers=reader_b_headers)
    assert wrong_domain_path_response.status_code == 404
