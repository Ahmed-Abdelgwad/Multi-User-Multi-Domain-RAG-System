from fastapi.testclient import TestClient
from src.entities.enums import DomainRole


def _create_domain(client: TestClient, headers, name=None):
    from uuid import uuid4
    return client.post("/domains/", headers=headers, json={"name": name or f"domain-{uuid4()}", "description": "t"})


def test_domain_admin_can_get_default_retrieval_config(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="rcfg-domain").json()["id"]

    response = client.get(f"/domains/{domain_id}/retrieval-config/", headers=platform_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["dense_weight"] == 1.0
    assert body["llm_routing_default"] == "api"


def test_domain_admin_can_update_retrieval_config(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="rcfg-domain-update").json()["id"]

    response = client.put(
        f"/domains/{domain_id}/retrieval-config/",
        headers=platform_admin_headers,
        json={
            "dense_weight": 0.5, "bm25_weight": 0.5, "graph_weight": 2.0,
            "llm_routing_default": "local",
            "llm_routing_sensitive_keywords": ["salary"],
            "confidence_threshold": 0.7,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["graph_weight"] == 2.0
    assert body["llm_routing_default"] == "local"


def test_update_retrieval_config_rejects_all_zero_weights(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="rcfg-domain-invalid").json()["id"]

    response = client.put(
        f"/domains/{domain_id}/retrieval-config/",
        headers=platform_admin_headers,
        json={
            "dense_weight": 0, "bm25_weight": 0, "graph_weight": 0,
            "llm_routing_default": "api",
            "confidence_threshold": 0.5,
        },
    )

    assert response.status_code == 400


def test_contributor_cannot_update_retrieval_config(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="rcfg-domain-rbac").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.put(
        f"/domains/{domain_id}/retrieval-config/",
        headers=contributor_headers,
        json={
            "dense_weight": 1.0, "bm25_weight": 1.0, "graph_weight": 1.0,
            "llm_routing_default": "api",
            "confidence_threshold": 0.5,
        },
    )

    assert response.status_code == 403


def test_contributor_cannot_read_retrieval_config(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="rcfg-domain-rbac-read").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.get(f"/domains/{domain_id}/retrieval-config/", headers=contributor_headers)

    assert response.status_code == 403


# --- /query -- RBAC only. answer_query's retrieve() step needs a real
# embedding model, spaCy, and pgvector, none of which exist in the
# sqlite fixture, so a real query can't be exercised locally (same
# stated limitation as the vector/graph retrievers themselves -- see
# the plan's Progress notes). build_retrieval_filter's permission check
# runs before any of that, though, so the RBAC edges are testable here.

def test_query_requires_authentication(client: TestClient):
    response = client.post("/query/", json={"query": "anything", "domain_ids": []})
    assert response.status_code == 401


def test_query_with_zero_permitted_domains_is_403(client: TestClient, auth_headers):
    from uuid import uuid4

    response = client.post(
        "/query/", headers=auth_headers, json={"query": "anything", "domain_ids": [str(uuid4())]}
    )
    assert response.status_code == 403
