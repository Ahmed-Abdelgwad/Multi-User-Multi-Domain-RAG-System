from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from src.entities.enums import DomainRole
from src.ontology import service as ontology_service


@pytest.fixture(autouse=True)
def _stub_reextraction(monkeypatch):
    # Celery isn't running under plain pytest -- same rationale as the
    # existing ingestion/chunking e2e stubs.
    monkeypatch.setattr(ontology_service, "_enqueue_reextraction", lambda domain_id: None)


def _create_domain(client: TestClient, headers, name=None):
    return client.post("/domains/", headers=headers, json={"name": name or f"domain-{uuid4()}", "description": "t"})


def test_domain_admin_can_create_and_get_active_schema(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="onto-domain").json()["id"]

    create_response = client.post(
        f"/domains/{domain_id}/ontology/",
        headers=platform_admin_headers,
        json={
            "node_types": ["Person", "Company"],
            "relation_types": [{"name": "works_at", "source_type": "Person", "target_type": "Company"}],
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["version"] == 1

    get_response = client.get(f"/domains/{domain_id}/ontology/", headers=platform_admin_headers)
    assert get_response.status_code == 200
    assert get_response.json()["version"] == 1
    assert get_response.json()["is_active"] is True


def test_get_active_schema_404s_when_none_created(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="onto-domain-empty").json()["id"]

    response = client.get(f"/domains/{domain_id}/ontology/", headers=platform_admin_headers)

    assert response.status_code == 404


def test_creating_new_version_deactivates_previous_and_lists_history(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="onto-domain-versions").json()["id"]

    client.post(f"/domains/{domain_id}/ontology/", headers=platform_admin_headers, json={"node_types": ["Person"]})
    client.post(
        f"/domains/{domain_id}/ontology/",
        headers=platform_admin_headers,
        json={"node_types": ["Person", "Company"]},
    )

    versions_response = client.get(f"/domains/{domain_id}/ontology/versions", headers=platform_admin_headers)
    assert versions_response.status_code == 200
    versions = versions_response.json()
    assert [v["version"] for v in versions] == [1, 2]
    assert [v["is_active"] for v in versions] == [False, True]


def test_create_schema_rejects_relation_with_undeclared_type(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="onto-domain-invalid").json()["id"]

    response = client.post(
        f"/domains/{domain_id}/ontology/",
        headers=platform_admin_headers,
        json={
            "node_types": ["Person"],
            "relation_types": [{"name": "works_at", "source_type": "Person", "target_type": "Company"}],
        },
    )

    assert response.status_code == 400


def test_import_schema_from_yaml_file(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="onto-domain-yaml").json()["id"]
    raw_yaml = (
        b"node_types:\n  - Person\n  - Company\n"
        b"relation_types:\n  - name: works_at\n    source_type: Person\n    target_type: Company\n"
    )

    response = client.post(
        f"/domains/{domain_id}/ontology/import",
        headers=platform_admin_headers,
        files={"file": ("schema.yaml", raw_yaml, "application/x-yaml")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["node_types"] == [
        {"name": "Person", "description": None, "threshold": None},
        {"name": "Company", "description": None, "threshold": None},
    ]
    assert body["relation_types"] == [{
        "name": "works_at", "source_type": "Person", "target_type": "Company",
        "description": None, "threshold": None,
    }]


def test_contributor_cannot_create_schema(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="onto-domain-rbac").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.post(
        f"/domains/{domain_id}/ontology/",
        headers=contributor_headers,
        json={"node_types": ["Person"]},
    )

    assert response.status_code == 403


def test_contributor_cannot_read_schema(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="onto-domain-rbac-read").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)
    client.post(f"/domains/{domain_id}/ontology/", headers=platform_admin_headers, json={"node_types": ["Person"]})

    response = client.get(f"/domains/{domain_id}/ontology/", headers=contributor_headers)

    assert response.status_code == 403


def test_user_without_role_cannot_access_ontology(client: TestClient, platform_admin_headers, auth_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="onto-domain-norole").json()["id"]

    response = client.get(f"/domains/{domain_id}/ontology/", headers=auth_headers)

    assert response.status_code == 403
