from uuid import uuid4
from fastapi.testclient import TestClient
from src.entities.enums import DomainRole
from src.evaluation import service as evaluation_service


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


def test_moderation_queue_item_includes_the_underlying_query_and_answer(client: TestClient, platform_admin_headers, db_session):
    # A moderation UI needs to show an admin what was actually asked/
    # answered, not just its scores -- confirms the enriched response
    # model (ModerationQueueItemResponse) actually reaches the client.
    domain_id = _create_domain(client, platform_admin_headers, name="modq-domain-enriched").json()["id"]
    query_log = _insert_query_log(db_session, domain_id, uuid4())
    evaluation = _insert_completed_evaluation(db_session, query_log.id)
    evaluation.flagged = True
    db_session.commit()

    response = client.get(f"/domains/{domain_id}/moderation-queue/", headers=platform_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["query"] == query_log.query
    assert body[0]["answer"] == query_log.answer
    assert "query_created_at" in body[0]


# --- POST /domains/{id}/moderation-queue/{query_log_id}/override (4.6) --
# RBAC + status/field shape; the snapshot/no-clobber correctness itself is
# covered by test_evaluation_service.py's sqlite-runnable unit tests.

def _insert_completed_evaluation(db_session, query_log_id):
    from uuid import uuid4
    from src.entities.evaluation_result import EvaluationResult
    from src.entities.enums import EvaluationStatus

    evaluation = EvaluationResult(
        id=uuid4(), query_log_id=query_log_id, status=EvaluationStatus.COMPLETED,
        faithfulness=0.9, relevance=0.9, completeness=0.9, citation_accuracy=0.9,
    )
    db_session.add(evaluation)
    db_session.commit()
    return evaluation


def _override_payload():
    return {"faithfulness": 0.1, "relevance": 0.1, "completeness": 0.1, "citation_accuracy": 0.1, "rationale": "human correction"}


def test_domain_admin_can_override_evaluation(client: TestClient, platform_admin_headers, db_session):
    domain_id = _create_domain(client, platform_admin_headers, name="override-domain").json()["id"]
    query_log = _insert_query_log(db_session, domain_id, uuid4())
    _insert_completed_evaluation(db_session, query_log.id)

    response = client.post(
        f"/domains/{domain_id}/moderation-queue/{query_log.id}/override",
        headers=platform_admin_headers, json=_override_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["faithfulness"] == 0.1
    assert body["override_rationale"] == "human correction"
    assert body["overridden_by"] is not None
    assert body["original_scores"] == {"faithfulness": 0.9, "relevance": 0.9, "completeness": 0.9, "citation_accuracy": 0.9}


def test_contributor_cannot_override_evaluation(client: TestClient, platform_admin_headers, make_user_with_role, db_session):
    domain_id = _create_domain(client, platform_admin_headers, name="override-domain-rbac").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)
    query_log = _insert_query_log(db_session, domain_id, uuid4())
    _insert_completed_evaluation(db_session, query_log.id)

    response = client.post(
        f"/domains/{domain_id}/moderation-queue/{query_log.id}/override",
        headers=contributor_headers, json=_override_payload(),
    )

    assert response.status_code == 403


def test_override_evaluation_404s_for_wrong_domain(client: TestClient, platform_admin_headers, db_session):
    domain_a = _create_domain(client, platform_admin_headers, name="override-domain-a").json()["id"]
    domain_b = _create_domain(client, platform_admin_headers, name="override-domain-b").json()["id"]
    query_log = _insert_query_log(db_session, domain_a, uuid4())
    _insert_completed_evaluation(db_session, query_log.id)

    response = client.post(
        f"/domains/{domain_b}/moderation-queue/{query_log.id}/override",
        headers=platform_admin_headers, json=_override_payload(),
    )

    assert response.status_code == 404


def test_cannot_override_evaluation_on_an_archived_domain(client: TestClient, platform_admin_headers, db_session):
    domain_id = _create_domain(client, platform_admin_headers, name="override-domain-archived").json()["id"]
    query_log = _insert_query_log(db_session, domain_id, uuid4())
    _insert_completed_evaluation(db_session, query_log.id)
    query_log_id = query_log.id  # captured before the archive call expires+detaches it
    client.post(f"/domains/{domain_id}/archive", headers=platform_admin_headers)

    response = client.post(
        f"/domains/{domain_id}/moderation-queue/{query_log_id}/override",
        headers=platform_admin_headers, json=_override_payload(),
    )

    assert response.status_code == 400


def test_override_evaluation_rejects_empty_rationale(client: TestClient, platform_admin_headers, db_session):
    domain_id = _create_domain(client, platform_admin_headers, name="override-domain-validation").json()["id"]
    query_log = _insert_query_log(db_session, domain_id, uuid4())
    _insert_completed_evaluation(db_session, query_log.id)
    payload = _override_payload()
    payload["rationale"] = ""

    response = client.post(
        f"/domains/{domain_id}/moderation-queue/{query_log.id}/override",
        headers=platform_admin_headers, json=payload,
    )

    assert response.status_code == 422


# --- POST /domains/{id}/moderation-queue/{query_log_id}/verdict (4.6 fix:
# distinct accept/reject, independent of override's numeric correction).

def test_domain_admin_can_set_evaluation_verdict(client: TestClient, platform_admin_headers, db_session):
    domain_id = _create_domain(client, platform_admin_headers, name="verdict-domain").json()["id"]
    query_log = _insert_query_log(db_session, domain_id, uuid4())
    _insert_completed_evaluation(db_session, query_log.id)

    response = client.post(
        f"/domains/{domain_id}/moderation-queue/{query_log.id}/verdict",
        headers=platform_admin_headers, json={"verdict": "rejected", "rationale": "not usable"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["human_verdict"] == "rejected"
    assert body["faithfulness"] == 0.9  # untouched by a verdict-only review
    assert body["overridden_by"] is not None


def test_contributor_cannot_set_evaluation_verdict(client: TestClient, platform_admin_headers, make_user_with_role, db_session):
    domain_id = _create_domain(client, platform_admin_headers, name="verdict-domain-rbac").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)
    query_log = _insert_query_log(db_session, domain_id, uuid4())
    _insert_completed_evaluation(db_session, query_log.id)

    response = client.post(
        f"/domains/{domain_id}/moderation-queue/{query_log.id}/verdict",
        headers=contributor_headers, json={"verdict": "accepted", "rationale": "looks fine"},
    )

    assert response.status_code == 403


def test_evaluation_verdict_rejects_invalid_value(client: TestClient, platform_admin_headers, db_session):
    domain_id = _create_domain(client, platform_admin_headers, name="verdict-domain-validation").json()["id"]
    query_log = _insert_query_log(db_session, domain_id, uuid4())
    _insert_completed_evaluation(db_session, query_log.id)

    response = client.post(
        f"/domains/{domain_id}/moderation-queue/{query_log.id}/verdict",
        headers=platform_admin_headers, json={"verdict": "maybe", "rationale": "unsure"},
    )

    assert response.status_code == 422


# --- GET /domains/{id}/quality-dashboard -- RBAC + shape only (real
# aggregation math is covered by test_evaluation_service.py's sqlite-
# runnable unit tests; no live-model dependency here either).

def test_domain_admin_can_read_empty_quality_dashboard(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="qdash-domain").json()["id"]

    response = client.get(f"/domains/{domain_id}/quality-dashboard/", headers=platform_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["window_days"] == 30
    assert body["by_dimension"]["faithfulness"]["sample_count"] == 0
    assert body["degrading_dimensions"] == []
    assert len(body["trend"]) == 6  # default trend_points
    assert body["golden_regression"]["item_count"] == 0
    assert body["golden_regression"]["last_run_at"] is None


def test_quality_dashboard_trend_points_param_controls_bucket_count(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="qdash-domain-trend").json()["id"]

    response = client.get(
        f"/domains/{domain_id}/quality-dashboard/?trend_points=3", headers=platform_admin_headers,
    )

    assert response.status_code == 200
    assert len(response.json()["trend"]) == 3


def test_quality_dashboard_rejects_out_of_range_trend_points(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="qdash-domain-trend-invalid").json()["id"]

    response = client.get(
        f"/domains/{domain_id}/quality-dashboard/?trend_points=0", headers=platform_admin_headers,
    )

    assert response.status_code == 422


def test_contributor_cannot_read_quality_dashboard(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="qdash-domain-rbac").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.get(f"/domains/{domain_id}/quality-dashboard/", headers=contributor_headers)

    assert response.status_code == 403


def test_quality_dashboard_rejects_out_of_range_window_days(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="qdash-domain-window").json()["id"]

    response = client.get(
        f"/domains/{domain_id}/quality-dashboard/?window_days=0", headers=platform_admin_headers,
    )

    assert response.status_code == 422  # FastAPI's own Query(ge=1) validation


def test_domain_admin_can_export_quality_dashboard_csv(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="qdash-domain-export").json()["id"]

    response = client.get(f"/domains/{domain_id}/quality-dashboard/export", headers=platform_admin_headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "route,dimension,mean,sample_count" in response.text
    assert "period_start,period_end,dimension,mean,sample_count" in response.text
    assert "golden_regression_item_count" in response.text


def test_contributor_cannot_export_quality_dashboard_csv(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="qdash-domain-export-rbac").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.get(f"/domains/{domain_id}/quality-dashboard/export", headers=contributor_headers)

    assert response.status_code == 403


# --- /domains/{id}/golden-qa -- CRUD + RBAC (real retrieval/judge calls
# happen only via run_golden_regression_for_domain, covered by
# test_evaluation_service.py's sqlite-runnable unit tests, not here).

def _golden_qa_payload(question="Where does Alice work?"):
    return {"question": question, "expected_answer": "Acme Corporation.", "expected_citations": ["c1"]}


def test_domain_admin_can_crud_golden_qa_items(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="golden-domain-crud").json()["id"]

    create_resp = client.post(f"/domains/{domain_id}/golden-qa/", headers=platform_admin_headers, json=_golden_qa_payload())
    assert create_resp.status_code == 201
    item_id = create_resp.json()["id"]

    list_resp = client.get(f"/domains/{domain_id}/golden-qa/", headers=platform_admin_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    get_resp = client.get(f"/domains/{domain_id}/golden-qa/{item_id}", headers=platform_admin_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["question"] == "Where does Alice work?"

    update_resp = client.put(
        f"/domains/{domain_id}/golden-qa/{item_id}", headers=platform_admin_headers,
        json=_golden_qa_payload(question="Updated question?"),
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["question"] == "Updated question?"

    delete_resp = client.delete(f"/domains/{domain_id}/golden-qa/{item_id}", headers=platform_admin_headers)
    assert delete_resp.status_code == 204
    assert client.get(f"/domains/{domain_id}/golden-qa/{item_id}", headers=platform_admin_headers).status_code == 404


def test_contributor_cannot_create_golden_qa_item(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="golden-domain-rbac-create").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.post(f"/domains/{domain_id}/golden-qa/", headers=contributor_headers, json=_golden_qa_payload())

    assert response.status_code == 403


def test_contributor_cannot_read_golden_qa_items(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="golden-domain-rbac-read").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.get(f"/domains/{domain_id}/golden-qa/", headers=contributor_headers)

    assert response.status_code == 403


def test_golden_qa_item_is_404_from_a_different_domain(client: TestClient, platform_admin_headers):
    domain_a = _create_domain(client, platform_admin_headers, name="golden-domain-a").json()["id"]
    domain_b = _create_domain(client, platform_admin_headers, name="golden-domain-b").json()["id"]
    item_id = client.post(f"/domains/{domain_a}/golden-qa/", headers=platform_admin_headers, json=_golden_qa_payload()).json()["id"]

    response = client.get(f"/domains/{domain_b}/golden-qa/{item_id}", headers=platform_admin_headers)

    assert response.status_code == 404


def test_domain_admin_can_trigger_golden_regression(client: TestClient, platform_admin_headers, monkeypatch):
    # A successful trigger enqueues run_golden_regression_for_domain_task --
    # stub it so this e2e test never tries to reach a real Celery broker.
    monkeypatch.setattr(evaluation_service, "enqueue_golden_regression", lambda domain_id: None)
    domain_id = _create_domain(client, platform_admin_headers, name="golden-domain-trigger").json()["id"]

    response = client.post(f"/domains/{domain_id}/golden-qa/run-regression", headers=platform_admin_headers)

    assert response.status_code == 202
    assert response.json() == {"status": "enqueued"}


def test_contributor_cannot_trigger_golden_regression(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="golden-domain-trigger-rbac").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.post(f"/domains/{domain_id}/golden-qa/run-regression", headers=contributor_headers)

    assert response.status_code == 403


def test_cannot_trigger_golden_regression_on_an_archived_domain(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="golden-domain-archived").json()["id"]
    client.post(f"/domains/{domain_id}/archive", headers=platform_admin_headers)

    response = client.post(f"/domains/{domain_id}/golden-qa/run-regression", headers=platform_admin_headers)

    assert response.status_code == 400
