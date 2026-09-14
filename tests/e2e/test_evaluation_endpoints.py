from fastapi.testclient import TestClient
from src.entities.enums import DomainRole


def _create_domain(client: TestClient, headers, name=None):
    from uuid import uuid4
    return client.post("/domains/", headers=headers, json={"name": name or f"domain-{uuid4()}", "description": "t"})


def test_domain_admin_can_get_default_evaluation_config(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="ecfg-domain").json()["id"]

    response = client.get(f"/domains/{domain_id}/evaluation-config/", headers=platform_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["flag_threshold"] == 0.5
    assert body["degradation_alert_threshold"] == 0.1


def test_domain_admin_can_update_evaluation_config(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="ecfg-domain-update").json()["id"]

    response = client.put(
        f"/domains/{domain_id}/evaluation-config/",
        headers=platform_admin_headers,
        json={"flag_threshold": 0.7, "degradation_alert_threshold": 0.2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["flag_threshold"] == 0.7
    assert body["degradation_alert_threshold"] == 0.2


def test_contributor_cannot_update_evaluation_config(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="ecfg-domain-rbac").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.put(
        f"/domains/{domain_id}/evaluation-config/",
        headers=contributor_headers,
        json={"flag_threshold": 0.5, "degradation_alert_threshold": 0.1},
    )

    assert response.status_code == 403


def test_contributor_cannot_read_evaluation_config(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="ecfg-domain-rbac-read").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.get(f"/domains/{domain_id}/evaluation-config/", headers=contributor_headers)

    assert response.status_code == 403


# --- GET /query/{id}/evaluation -- pgvector/spaCy/Neo4j-free RBAC/status
# checks only (same stated limitation as /query itself: a real query_log
# is inserted directly rather than round-tripped through /query, which
# needs the real model stack this sqlite fixture doesn't have).

def _insert_query_log(db_session, domain_id, user_id):
    from uuid import uuid4
    from src.entities.query_log import QueryLog
    from src.entities.enums import LLMRoute

    query_log = QueryLog(
        id=uuid4(), user_id=user_id, domain_ids=[str(domain_id)],
        query="q", answer="a", route=LLMRoute.API, confidence=0.9, sources=[], graph_context=[],
    )
    db_session.add(query_log)
    db_session.commit()
    return query_log


def test_querying_user_sees_pending_before_evaluation_completes(client: TestClient, platform_admin_headers, make_user_with_role, db_session):
    domain_id = _create_domain(client, platform_admin_headers, name="qeval-domain").json()["id"]
    reader_headers, reader_id = make_user_with_role(domain_id, DomainRole.READER)
    query_log = _insert_query_log(db_session, domain_id, reader_id)

    response = client.get(f"/query/{query_log.id}/evaluation", headers=reader_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["faithfulness"] is None


def test_unrelated_user_cannot_see_someone_elses_query_evaluation(client: TestClient, platform_admin_headers, make_user_with_role, db_session):
    domain_id = _create_domain(client, platform_admin_headers, name="qeval-domain-rbac").json()["id"]
    _, owner_id = make_user_with_role(domain_id, DomainRole.READER)
    stranger_headers, _ = make_user_with_role(domain_id, DomainRole.READER)
    query_log = _insert_query_log(db_session, domain_id, owner_id)

    response = client.get(f"/query/{query_log.id}/evaluation", headers=stranger_headers)

    assert response.status_code == 403


def test_domain_admin_can_see_any_query_evaluation_in_their_domain(client: TestClient, platform_admin_headers, make_user_with_role, db_session):
    domain_id = _create_domain(client, platform_admin_headers, name="qeval-domain-admin").json()["id"]
    _, owner_id = make_user_with_role(domain_id, DomainRole.READER)
    admin_headers, _ = make_user_with_role(domain_id, DomainRole.ADMIN)
    query_log = _insert_query_log(db_session, domain_id, owner_id)

    response = client.get(f"/query/{query_log.id}/evaluation", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_query_evaluation_requires_authentication(client: TestClient):
    from uuid import uuid4
    response = client.get(f"/query/{uuid4()}/evaluation")
    assert response.status_code == 401


# --- GET /domains/{id}/moderation-queue -- RBAC only (empty queue is the
# only state reachable without a real judge run in this sqlite fixture).

def test_domain_admin_can_read_empty_moderation_queue(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="modq-domain").json()["id"]

    response = client.get(f"/domains/{domain_id}/moderation-queue/", headers=platform_admin_headers)

    assert response.status_code == 200
    assert response.json() == []


def test_contributor_cannot_read_moderation_queue(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="modq-domain-rbac").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.get(f"/domains/{domain_id}/moderation-queue/", headers=contributor_headers)

    assert response.status_code == 403
