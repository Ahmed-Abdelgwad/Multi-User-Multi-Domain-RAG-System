import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from langchain_core.documents import Document
from src.entities.domain import Domain
from src.entities.user_domain_role import UserDomainRole
from src.entities.query_log import QueryLog
from src.entities.evaluation_result import EvaluationResult
from src.entities.enums import DomainRole, LLMRoute, JudgeProvider, EvaluationStatus, HumanVerdict
from src.auth.models import TokenData
from src.exceptions import (
    InsufficientPermissionsError, JudgeUnavailableError, InvalidDashboardWindowError, GoldenQAItemNotFoundError,
    DomainArchivedError, QueryLogNotFoundError,
)
from src.evaluation import service, models, judge


def _make_domain(db_session) -> Domain:
    domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4())
    db_session.add(domain)
    db_session.commit()
    return domain


def _grant(db_session, user_id, domain_id, role: DomainRole):
    db_session.add(UserDomainRole(id=uuid4(), user_id=user_id, domain_id=domain_id, role=role))
    db_session.commit()


def _make_query_log(db_session, domain_ids, user_id=None, golden_qa_item_id=None) -> QueryLog:
    query_log = QueryLog(
        id=uuid4(), user_id=user_id or uuid4(), domain_ids=[str(d) for d in domain_ids],
        query="Where does Alice work?", answer="Alice works at Acme [1].",
        route=LLMRoute.API, confidence=0.9,
        sources=[{"chunk_id": "c1", "domain_id": str(domain_ids[0]), "domain_name": "d",
                  "content_type": "text", "content": "Alice Johnson works at Acme Corporation.", "score": 0.9}],
        graph_context=[], golden_qa_item_id=golden_qa_item_id,
    )
    db_session.add(query_log)
    db_session.commit()
    return query_log


_SCORES = judge.JudgeScores(
    faithfulness=0.9, faithfulness_rationale="ok",
    relevance=0.9, relevance_rationale="ok",
    completeness=0.9, completeness_rationale="ok",
    citation_accuracy=0.9, citation_accuracy_rationale="ok",
)


# --- create_query_log ---

def test_create_query_log_stores_chunk_content_alongside_metadata(db_session):
    user_id = uuid4()
    domain = _make_domain(db_session)
    doc = Document(
        page_content="Alice Johnson works at Acme Corporation.",
        metadata={"chunk_id": "c1", "domain_id": str(domain.id), "domain_name": domain.name,
                  "content_type": "text", "vector_score": 0.9},
    )
    result = {
        "documents": [doc], "permitted_domain_ids": [domain.id],
        "answer": "Alice works at Acme [1].", "route": LLMRoute.API, "confidence": 0.9, "graph_context": [],
    }

    query_log = service.create_query_log(db_session, TokenData(user_id=str(user_id)), "Where does Alice work?", result)

    assert query_log.user_id == user_id
    assert query_log.domain_ids == [str(domain.id)]
    assert query_log.sources[0]["content"] == "Alice Johnson works at Acme Corporation."
    assert query_log.sources[0]["score"] == 0.9


# --- evaluate_query_log ---

def test_evaluate_query_log_completes_and_flags_below_threshold(db_session, monkeypatch):
    domain = _make_domain(db_session)
    service.update_evaluation_config(db_session, domain.id, models.DomainEvaluationConfigUpdate(
        flag_threshold=0.95, degradation_alert_threshold=0.1,
    ))
    query_log = _make_query_log(db_session, [domain.id])
    db_session.add(EvaluationResult(id=uuid4(), query_log_id=query_log.id))
    db_session.commit()

    monkeypatch.setattr(service, "get_settings", lambda: type("S", (), {
        "judge_provider": "mercury", "inception_api_key": "k",
        "judge_llm_enabled": False, "judge_api_model_name": "mercury-2.5", "judge_llm_model_name": "qwen3:4b",
    })())
    monkeypatch.setattr(judge, "evaluate_answer", lambda *a, **kw: _SCORES)

    evaluation = service.evaluate_query_log(db_session, query_log.id)

    assert evaluation.status == EvaluationStatus.COMPLETED
    assert evaluation.faithfulness == 0.9
    assert evaluation.flagged is True  # 0.9 < the domain's 0.95 threshold
    assert evaluation.judge_provider == JudgeProvider.MERCURY
    assert evaluation.judge_model_version == "mercury-2.5"


def test_evaluate_query_log_uses_strictest_threshold_across_domains(db_session, monkeypatch):
    # The exact multi-domain gap caught in review: a query spanning a lax
    # domain (threshold 0.1) and a strict one (threshold 0.95) must flag
    # using the STRICT domain's threshold, not just the first domain's.
    lax_domain, strict_domain = _make_domain(db_session), _make_domain(db_session)
    service.update_evaluation_config(db_session, lax_domain.id, models.DomainEvaluationConfigUpdate(
        flag_threshold=0.1, degradation_alert_threshold=0.1,
    ))
    service.update_evaluation_config(db_session, strict_domain.id, models.DomainEvaluationConfigUpdate(
        flag_threshold=0.95, degradation_alert_threshold=0.1,
    ))
    # lax domain listed FIRST -- a naive domain_ids[0] lookup would miss the strict threshold entirely.
    query_log = _make_query_log(db_session, [lax_domain.id, strict_domain.id])
    db_session.add(EvaluationResult(id=uuid4(), query_log_id=query_log.id))
    db_session.commit()

    monkeypatch.setattr(service, "get_settings", lambda: type("S", (), {
        "judge_provider": "mercury", "inception_api_key": "k",
        "judge_llm_enabled": False, "judge_api_model_name": "mercury-2.5", "judge_llm_model_name": "qwen3:4b",
    })())
    monkeypatch.setattr(judge, "evaluate_answer", lambda *a, **kw: _SCORES)

    evaluation = service.evaluate_query_log(db_session, query_log.id)

    assert evaluation.flagged is True  # 0.9 < strict_domain's 0.95, even though lax_domain (0.1) is listed first


def test_evaluate_query_log_skips_when_mercury_key_missing(db_session, monkeypatch):
    domain = _make_domain(db_session)
    query_log = _make_query_log(db_session, [domain.id])
    db_session.add(EvaluationResult(id=uuid4(), query_log_id=query_log.id))
    db_session.commit()

    monkeypatch.setattr(service, "get_settings", lambda: type("S", (), {
        "judge_provider": "mercury", "inception_api_key": None, "judge_llm_enabled": False,
    })())

    def _boom(*a, **kw):
        raise AssertionError("judge.evaluate_answer should not be called when the provider is unusable")
    monkeypatch.setattr(judge, "evaluate_answer", _boom)

    evaluation = service.evaluate_query_log(db_session, query_log.id)

    assert evaluation.status == EvaluationStatus.SKIPPED
    assert "INCEPTION_API_KEY" in evaluation.error_message


def test_evaluate_query_log_marks_failed_on_judge_error(db_session, monkeypatch):
    domain = _make_domain(db_session)
    query_log = _make_query_log(db_session, [domain.id])
    db_session.add(EvaluationResult(id=uuid4(), query_log_id=query_log.id))
    db_session.commit()

    monkeypatch.setattr(service, "get_settings", lambda: type("S", (), {
        "judge_provider": "mercury", "inception_api_key": "k", "judge_llm_enabled": False,
    })())

    def _boom(*a, **kw):
        raise JudgeUnavailableError("provider down")
    monkeypatch.setattr(judge, "evaluate_answer", _boom)

    evaluation = service.evaluate_query_log(db_session, query_log.id)

    assert evaluation.status == EvaluationStatus.FAILED
    assert evaluation.error_message == "provider down"


# --- get_evaluation (visibility) ---

def test_get_evaluation_visible_to_the_querying_user(db_session):
    domain = _make_domain(db_session)
    user_id = uuid4()
    query_log = _make_query_log(db_session, [domain.id], user_id=user_id)

    assert service.get_evaluation(db_session, TokenData(user_id=str(user_id)), query_log.id) is None


def test_get_evaluation_visible_to_a_domain_admin_of_one_of_its_domains(db_session):
    domain = _make_domain(db_session)
    query_log = _make_query_log(db_session, [domain.id])
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)

    assert service.get_evaluation(db_session, TokenData(user_id=str(admin_id)), query_log.id) is None


def test_get_evaluation_rejects_an_unrelated_user(db_session):
    domain = _make_domain(db_session)
    query_log = _make_query_log(db_session, [domain.id])
    stranger_id = uuid4()

    with pytest.raises(InsufficientPermissionsError):
        service.get_evaluation(db_session, TokenData(user_id=str(stranger_id)), query_log.id)


def test_get_evaluation_rejects_a_reader_who_is_not_the_querying_user(db_session):
    domain = _make_domain(db_session)
    query_log = _make_query_log(db_session, [domain.id])
    reader_id = uuid4()
    _grant(db_session, reader_id, domain.id, DomainRole.READER)  # reader, not admin -- still not enough

    with pytest.raises(InsufficientPermissionsError):
        service.get_evaluation(db_session, TokenData(user_id=str(reader_id)), query_log.id)


# --- get_moderation_queue ---

def test_get_moderation_queue_returns_flagged_unoverridden_for_the_right_domain_only(db_session):
    domain_a, domain_b = _make_domain(db_session), _make_domain(db_session)
    log_a = _make_query_log(db_session, [domain_a.id])
    log_b = _make_query_log(db_session, [domain_b.id])
    log_a_overridden = _make_query_log(db_session, [domain_a.id])

    db_session.add(EvaluationResult(id=uuid4(), query_log_id=log_a.id, status=EvaluationStatus.COMPLETED, flagged=True))
    db_session.add(EvaluationResult(id=uuid4(), query_log_id=log_b.id, status=EvaluationStatus.COMPLETED, flagged=True))
    db_session.add(EvaluationResult(
        id=uuid4(), query_log_id=log_a_overridden.id, status=EvaluationStatus.COMPLETED,
        flagged=True, overridden_by=uuid4(),
    ))
    db_session.commit()

    queue = service.get_moderation_queue(db_session, domain_a.id)

    assert [e.query_log_id for e in queue] == [log_a.id]


def test_get_or_create_evaluation_config_creates_defaults(db_session):
    domain = _make_domain(db_session)

    config = service.get_or_create_evaluation_config(db_session, domain.id)

    assert config.domain_id == domain.id
    assert config.flag_threshold == 0.5
    assert config.degradation_alert_threshold == 0.1


def test_get_or_create_evaluation_config_is_idempotent(db_session):
    domain = _make_domain(db_session)

    first = service.get_or_create_evaluation_config(db_session, domain.id)
    second = service.get_or_create_evaluation_config(db_session, domain.id)

    assert first.id == second.id


def test_update_evaluation_config_persists_new_values(db_session):
    domain = _make_domain(db_session)

    config = service.update_evaluation_config(
        db_session, domain.id,
        models.DomainEvaluationConfigUpdate(flag_threshold=0.7, degradation_alert_threshold=0.2),
    )

    assert config.flag_threshold == 0.7
    assert config.degradation_alert_threshold == 0.2


# --- get_quality_dashboard (4.4) ---

def _make_evaluation(db_session, domain_id, *, updated_at, route=LLMRoute.API, faithfulness=0.9,
                      relevance=0.9, completeness=0.9, citation_accuracy=0.9, status=EvaluationStatus.COMPLETED,
                      golden_qa_item_id=None, flagged=False, query_created_at=None):
    query_log = _make_query_log(db_session, [domain_id], golden_qa_item_id=golden_qa_item_id)
    query_log.route = route
    if query_created_at is not None:
        query_log.created_at = query_created_at
    db_session.commit()
    evaluation = EvaluationResult(
        id=uuid4(), query_log_id=query_log.id, status=status,
        faithfulness=faithfulness, relevance=relevance, completeness=completeness,
        citation_accuracy=citation_accuracy, flagged=flagged,
    )
    db_session.add(evaluation)
    db_session.commit()
    evaluation.updated_at = updated_at  # backdate for windowing, after the row-default fires
    db_session.commit()
    db_session.refresh(evaluation)
    return evaluation


def test_get_quality_dashboard_empty_domain_has_no_samples(db_session):
    domain = _make_domain(db_session)

    dashboard = service.get_quality_dashboard(db_session, domain.id)

    assert dashboard.by_dimension["faithfulness"].mean is None
    assert dashboard.by_dimension["faithfulness"].sample_count == 0
    assert dashboard.by_route == {}
    assert dashboard.degrading_dimensions == []


def test_get_quality_dashboard_rejects_non_positive_window(db_session):
    domain = _make_domain(db_session)

    with pytest.raises(InvalidDashboardWindowError):
        service.get_quality_dashboard(db_session, domain.id, window_days=0)


def test_get_quality_dashboard_rejects_window_beyond_max(db_session):
    domain = _make_domain(db_session)

    with pytest.raises(InvalidDashboardWindowError):
        service.get_quality_dashboard(db_session, domain.id, window_days=366)


def test_get_quality_dashboard_computes_means_and_segments_by_route(db_session):
    domain = _make_domain(db_session)
    now = datetime.now(timezone.utc)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), route=LLMRoute.API, faithfulness=1.0)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), route=LLMRoute.API, faithfulness=0.8)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), route=LLMRoute.LOCAL, faithfulness=0.5)

    dashboard = service.get_quality_dashboard(db_session, domain.id, window_days=30)

    assert dashboard.by_dimension["faithfulness"].sample_count == 3
    assert dashboard.by_dimension["faithfulness"].mean == pytest.approx((1.0 + 0.8 + 0.5) / 3)
    assert dashboard.by_route["api"]["faithfulness"].mean == pytest.approx(0.9)
    assert dashboard.by_route["local"]["faithfulness"].mean == pytest.approx(0.5)


def test_get_quality_dashboard_excludes_evaluations_outside_the_window(db_session):
    domain = _make_domain(db_session)
    now = datetime.now(timezone.utc)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=90), faithfulness=0.1)

    dashboard = service.get_quality_dashboard(db_session, domain.id, window_days=30)

    assert dashboard.by_dimension["faithfulness"].sample_count == 0


def test_get_quality_dashboard_excludes_non_completed_evaluations(db_session):
    domain = _make_domain(db_session)
    now = datetime.now(timezone.utc)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), status=EvaluationStatus.SKIPPED,
                      faithfulness=None, relevance=None, completeness=None, citation_accuracy=None)

    dashboard = service.get_quality_dashboard(db_session, domain.id, window_days=30)

    assert dashboard.by_dimension["faithfulness"].sample_count == 0


def test_get_quality_dashboard_flags_degrading_dimension_with_enough_samples(db_session):
    domain = _make_domain(db_session)
    service.update_evaluation_config(db_session, domain.id, models.DomainEvaluationConfigUpdate(
        flag_threshold=0.5, degradation_alert_threshold=0.1,
    ))
    now = datetime.now(timezone.utc)
    for _ in range(3):
        _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=45), faithfulness=0.9)
    for _ in range(3):
        _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), faithfulness=0.5)

    dashboard = service.get_quality_dashboard(db_session, domain.id, window_days=30)

    assert "faithfulness" in dashboard.degrading_dimensions


def test_get_quality_dashboard_does_not_flag_degradation_with_too_few_samples(db_session):
    # Same drop as the test above (0.9 -> 0.5, threshold 0.1) but only ONE
    # sample per window -- must NOT be reported as degrading, since a
    # single-sample mean swing is noise, not a trend.
    domain = _make_domain(db_session)
    service.update_evaluation_config(db_session, domain.id, models.DomainEvaluationConfigUpdate(
        flag_threshold=0.5, degradation_alert_threshold=0.1,
    ))
    now = datetime.now(timezone.utc)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=45), faithfulness=0.9)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), faithfulness=0.5)

    dashboard = service.get_quality_dashboard(db_session, domain.id, window_days=30)

    assert "faithfulness" not in dashboard.degrading_dimensions


def test_get_quality_dashboard_does_not_flag_improvement(db_session):
    domain = _make_domain(db_session)
    service.update_evaluation_config(db_session, domain.id, models.DomainEvaluationConfigUpdate(
        flag_threshold=0.5, degradation_alert_threshold=0.1,
    ))
    now = datetime.now(timezone.utc)
    for _ in range(3):
        _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=45), faithfulness=0.5)
    for _ in range(3):
        _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), faithfulness=0.9)

    dashboard = service.get_quality_dashboard(db_session, domain.id, window_days=30)

    assert "faithfulness" not in dashboard.degrading_dimensions


def test_export_quality_dashboard_csv_contains_dimension_rows(db_session):
    domain = _make_domain(db_session)
    now = datetime.now(timezone.utc)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), faithfulness=0.9)

    csv_text = service.export_quality_dashboard_csv(db_session, domain.id, window_days=30)

    assert "route,dimension,mean,sample_count" in csv_text
    assert "faithfulness" in csv_text
    assert "all,faithfulness,0.9,1" in csv_text


# --- get_quality_dashboard trend + golden-regression surfacing (4.4/4.5 fix) ---

def test_get_quality_dashboard_rejects_invalid_trend_points(db_session):
    domain = _make_domain(db_session)

    with pytest.raises(InvalidDashboardWindowError):
        service.get_quality_dashboard(db_session, domain.id, trend_points=0)
    with pytest.raises(InvalidDashboardWindowError):
        service.get_quality_dashboard(db_session, domain.id, trend_points=25)


def test_get_quality_dashboard_trend_has_one_bucket_per_trend_point_oldest_first(db_session):
    domain = _make_domain(db_session)
    now = datetime.now(timezone.utc)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), faithfulness=0.5)  # bucket 0 (current)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=35), faithfulness=0.7)  # bucket 1
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=65), faithfulness=0.9)  # bucket 2

    dashboard = service.get_quality_dashboard(db_session, domain.id, window_days=30, trend_points=3)

    assert len(dashboard.trend) == 3
    # oldest first: bucket 2's data lands in trend[0], bucket 0's (current) in trend[-1]
    assert dashboard.trend[0].by_dimension["faithfulness"].mean == 0.9
    assert dashboard.trend[1].by_dimension["faithfulness"].mean == 0.7
    assert dashboard.trend[2].by_dimension["faithfulness"].mean == 0.5
    assert dashboard.trend[-1].period_start < dashboard.trend[-1].period_end


def test_get_quality_dashboard_trend_most_recent_bucket_matches_top_level_by_dimension(db_session):
    domain = _make_domain(db_session)
    now = datetime.now(timezone.utc)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), faithfulness=0.42)

    dashboard = service.get_quality_dashboard(db_session, domain.id, window_days=30, trend_points=4)

    assert dashboard.trend[-1].by_dimension["faithfulness"].mean == dashboard.by_dimension["faithfulness"].mean == 0.42


def test_get_quality_dashboard_excludes_golden_regression_traffic_from_live_aggregates(db_session):
    domain = _make_domain(db_session)
    now = datetime.now(timezone.utc)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), faithfulness=0.9)  # live
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), faithfulness=0.1,
                      golden_qa_item_id=uuid4())  # regression -- must not skew the live mean

    dashboard = service.get_quality_dashboard(db_session, domain.id, window_days=30)

    assert dashboard.by_dimension["faithfulness"].sample_count == 1
    assert dashboard.by_dimension["faithfulness"].mean == 0.9


def test_get_golden_regression_summary_uses_only_the_latest_run_per_item(db_session):
    domain = _make_domain(db_session)
    item_id = uuid4()
    now = datetime.now(timezone.utc)
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=10), faithfulness=0.2,
                      golden_qa_item_id=item_id, query_created_at=now - timedelta(days=10))
    _make_evaluation(db_session, domain.id, updated_at=now - timedelta(days=1), faithfulness=0.8,
                      golden_qa_item_id=item_id, query_created_at=now - timedelta(days=1), flagged=True)

    summary = service.get_golden_regression_summary(db_session, domain.id)

    assert summary.item_count == 1  # one golden item, deduped to its latest run
    assert summary.flagged_count == 1
    assert summary.by_dimension["faithfulness"].mean == 0.8  # the LATEST run's score, not the stale 0.2
    assert summary.last_run_at is not None


def test_get_golden_regression_summary_empty_when_no_golden_traffic(db_session):
    domain = _make_domain(db_session)
    _make_evaluation(db_session, domain.id, updated_at=datetime.now(timezone.utc), faithfulness=0.9)  # live only

    summary = service.get_golden_regression_summary(db_session, domain.id)

    assert summary.item_count == 0
    assert summary.last_run_at is None


def test_get_quality_dashboard_includes_golden_regression_summary(db_session):
    domain = _make_domain(db_session)
    _make_evaluation(db_session, domain.id, updated_at=datetime.now(timezone.utc), faithfulness=0.6,
                      golden_qa_item_id=uuid4())

    dashboard = service.get_quality_dashboard(db_session, domain.id)

    assert dashboard.golden_regression.item_count == 1
    assert dashboard.golden_regression.by_dimension["faithfulness"].mean == 0.6


# --- golden QA CRUD (4.5) ---

def test_create_golden_qa_item_persists_fields(db_session):
    domain = _make_domain(db_session)
    user_id = uuid4()

    item = service.create_golden_qa_item(db_session, domain.id, TokenData(user_id=str(user_id)), models.GoldenQAItemCreate(
        question="Where does Alice work?", expected_answer="Acme Corporation.", expected_citations=["c1"],
    ))

    assert item.domain_id == domain.id
    assert item.created_by == user_id
    assert item.expected_citations == ["c1"]


def test_list_golden_qa_items_scoped_to_domain(db_session):
    domain_a, domain_b = _make_domain(db_session), _make_domain(db_session)
    user_id = uuid4()
    service.create_golden_qa_item(db_session, domain_a.id, TokenData(user_id=str(user_id)),
                                   models.GoldenQAItemCreate(question="q1", expected_answer="a1"))
    service.create_golden_qa_item(db_session, domain_b.id, TokenData(user_id=str(user_id)),
                                   models.GoldenQAItemCreate(question="q2", expected_answer="a2"))

    items = service.list_golden_qa_items(db_session, domain_a.id)

    assert [i.question for i in items] == ["q1"]


def test_get_golden_qa_item_404s_for_wrong_domain(db_session):
    domain_a, domain_b = _make_domain(db_session), _make_domain(db_session)
    user_id = uuid4()
    item = service.create_golden_qa_item(db_session, domain_a.id, TokenData(user_id=str(user_id)),
                                          models.GoldenQAItemCreate(question="q1", expected_answer="a1"))

    with pytest.raises(GoldenQAItemNotFoundError):
        service.get_golden_qa_item(db_session, domain_b.id, item.id)


def test_update_golden_qa_item_persists_new_values(db_session):
    domain = _make_domain(db_session)
    user_id = uuid4()
    item = service.create_golden_qa_item(db_session, domain.id, TokenData(user_id=str(user_id)),
                                          models.GoldenQAItemCreate(question="q1", expected_answer="a1"))

    updated = service.update_golden_qa_item(db_session, domain.id, item.id, models.GoldenQAItemCreate(
        question="q2", expected_answer="a2", expected_citations=["c9"],
    ))

    assert updated.question == "q2"
    assert updated.expected_citations == ["c9"]


def test_delete_golden_qa_item_removes_it(db_session):
    domain = _make_domain(db_session)
    user_id = uuid4()
    item = service.create_golden_qa_item(db_session, domain.id, TokenData(user_id=str(user_id)),
                                          models.GoldenQAItemCreate(question="q1", expected_answer="a1"))

    service.delete_golden_qa_item(db_session, domain.id, item.id)

    with pytest.raises(GoldenQAItemNotFoundError):
        service.get_golden_qa_item(db_session, domain.id, item.id)


# --- run_golden_regression_for_domain (4.5) ---

def _fake_retrieve_result(domain_id):
    doc = Document(
        page_content="Alice Johnson works at Acme Corporation.",
        metadata={"chunk_id": "c1", "domain_id": str(domain_id), "domain_name": "d",
                  "content_type": "text", "vector_score": 0.9},
    )
    return {
        "query": "q", "permitted_domain_ids": [domain_id], "entities": [], "documents": [doc],
        "graph_context": [], "confidence": 0.9, "low_confidence": False, "config": object(),
    }


def _stub_judge_and_settings(monkeypatch):
    monkeypatch.setattr(service, "get_settings", lambda: type("S", (), {
        "judge_provider": "mercury", "inception_api_key": "k", "judge_llm_enabled": False,
        "judge_api_model_name": "mercury-2.5", "judge_llm_model_name": "qwen3:4b",
    })())
    monkeypatch.setattr(judge, "evaluate_answer", lambda *a, **kw: _SCORES)


def test_run_golden_regression_creates_reference_aware_evaluation(db_session, monkeypatch):
    import src.retrieval.service as retrieval_service
    import src.generation.service as generation_service

    domain = _make_domain(db_session)
    creator_id = uuid4()
    item = service.create_golden_qa_item(db_session, domain.id, TokenData(user_id=str(creator_id)),
                                          models.GoldenQAItemCreate(question="Where does Alice work?",
                                                                     expected_answer="Acme Corporation.",
                                                                     expected_citations=["c1"]))

    monkeypatch.setattr(retrieval_service, "_retrieve_for_permitted_domains",
                         lambda db, q, permitted: _fake_retrieve_result(domain.id))
    monkeypatch.setattr(generation_service, "generate_answer",
                         lambda q, docs, cfg: ("Alice works at Acme [1].", LLMRoute.API))
    _stub_judge_and_settings(monkeypatch)

    query_logs = service.run_golden_regression_for_domain(db_session, domain.id)

    assert len(query_logs) == 1
    assert query_logs[0].golden_qa_item_id == item.id
    assert query_logs[0].user_id == creator_id  # attribution only, not a permission check

    evaluation = db_session.query(EvaluationResult).filter(EvaluationResult.query_log_id == query_logs[0].id).first()
    assert evaluation.status == EvaluationStatus.COMPLETED


def test_run_golden_regression_does_not_require_creator_to_still_hold_a_role(db_session, monkeypatch):
    # Regression coverage for the gap flagged in review: run_golden_regression_for_domain
    # must not go through the RBAC-checked retrieve() -- proven here by a creator who
    # was NEVER granted any role in the domain, and by making retrieve() itself blow up
    # if it's ever called.
    import src.retrieval.service as retrieval_service
    import src.generation.service as generation_service

    domain = _make_domain(db_session)
    creator_id = uuid4()  # deliberately never granted any role in `domain`
    service.create_golden_qa_item(db_session, domain.id, TokenData(user_id=str(creator_id)),
                                   models.GoldenQAItemCreate(question="q", expected_answer="a"))

    def _boom_if_rbac_checked(*a, **kw):
        raise AssertionError("must not call the RBAC-checked retrieve()")
    monkeypatch.setattr(retrieval_service, "retrieve", _boom_if_rbac_checked)
    monkeypatch.setattr(retrieval_service, "_retrieve_for_permitted_domains",
                         lambda db, q, permitted: _fake_retrieve_result(domain.id))
    monkeypatch.setattr(generation_service, "generate_answer", lambda q, docs, cfg: ("a", LLMRoute.API))
    _stub_judge_and_settings(monkeypatch)

    query_logs = service.run_golden_regression_for_domain(db_session, domain.id)

    assert len(query_logs) == 1


def test_run_golden_regression_isolates_one_items_failure(db_session, monkeypatch):
    import src.retrieval.service as retrieval_service
    import src.generation.service as generation_service

    domain = _make_domain(db_session)
    creator_id = uuid4()
    service.create_golden_qa_item(db_session, domain.id, TokenData(user_id=str(creator_id)),
                                   models.GoldenQAItemCreate(question="q1", expected_answer="a1"))
    item2 = service.create_golden_qa_item(db_session, domain.id, TokenData(user_id=str(creator_id)),
                                           models.GoldenQAItemCreate(question="q2", expected_answer="a2"))

    def _flaky_retrieve(db, q, permitted):
        if q == "q1":
            raise RuntimeError("transient retrieval failure")
        return _fake_retrieve_result(domain.id)
    monkeypatch.setattr(retrieval_service, "_retrieve_for_permitted_domains", _flaky_retrieve)
    monkeypatch.setattr(generation_service, "generate_answer", lambda q, docs, cfg: ("a", LLMRoute.API))
    _stub_judge_and_settings(monkeypatch)

    query_logs = service.run_golden_regression_for_domain(db_session, domain.id)

    assert len(query_logs) == 1
    assert query_logs[0].golden_qa_item_id == item2.id


def test_run_golden_regression_rejects_archived_domain(db_session):
    from src.domains.service import archive_domain
    domain = _make_domain(db_session)
    archive_domain(db_session, domain.id, uuid4())

    with pytest.raises(DomainArchivedError):
        service.run_golden_regression_for_domain(db_session, domain.id)


def test_trigger_golden_regression_rejects_archived_domain_without_enqueuing(db_session, monkeypatch):
    # Unlike _enqueue_reindex/_enqueue_reextraction (only ever reached
    # after a config-mutation call site already checked archived status),
    # this is a bare trigger endpoint -- must reject BEFORE dispatching to
    # Celery, not let the archived domain silently 202 and fail invisibly
    # inside the task later.
    from src.domains.service import archive_domain
    domain = _make_domain(db_session)
    archive_domain(db_session, domain.id, uuid4())

    def _boom_if_enqueued(domain_id):
        raise AssertionError("must not enqueue a regression run for an archived domain")
    monkeypatch.setattr(service, "enqueue_golden_regression", _boom_if_enqueued)

    with pytest.raises(DomainArchivedError):
        service.trigger_golden_regression(db_session, domain.id)


# --- override_evaluation (4.6) ---

def _make_completed_evaluation(db_session, query_log_id, **scores):
    evaluation = EvaluationResult(
        id=uuid4(), query_log_id=query_log_id, status=EvaluationStatus.COMPLETED,
        faithfulness=scores.get("faithfulness", 0.9), relevance=scores.get("relevance", 0.9),
        completeness=scores.get("completeness", 0.9), citation_accuracy=scores.get("citation_accuracy", 0.9),
        judge_provider=JudgeProvider.MERCURY, judge_model_version="mercury-2.5",
    )
    db_session.add(evaluation)
    db_session.commit()
    return evaluation


def _override_request(**scores):
    return models.EvaluationOverrideRequest(
        faithfulness=scores.get("faithfulness", 0.2), relevance=scores.get("relevance", 0.2),
        completeness=scores.get("completeness", 0.2), citation_accuracy=scores.get("citation_accuracy", 0.2),
        rationale=scores.get("rationale", "human correction"),
    )


def test_override_evaluation_snapshots_original_scores_and_applies_correction(db_session):
    domain = _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain.id])
    _make_completed_evaluation(db_session, query_log.id, faithfulness=0.9, relevance=0.9, completeness=0.9, citation_accuracy=0.9)

    result = service.override_evaluation(
        db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)), _override_request(faithfulness=0.1),
    )

    assert result.faithfulness == 0.1
    assert result.status == EvaluationStatus.COMPLETED
    assert result.overridden_by == admin_id
    assert result.override_rationale == "human correction"
    assert result.overridden_at is not None
    assert result.original_scores == {"faithfulness": 0.9, "relevance": 0.9, "completeness": 0.9, "citation_accuracy": 0.9}


def test_override_evaluation_second_override_preserves_true_original_scores(db_session):
    domain = _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain.id])
    _make_completed_evaluation(db_session, query_log.id, faithfulness=0.9)

    service.override_evaluation(db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)), _override_request(faithfulness=0.1))
    result = service.override_evaluation(db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)), _override_request(faithfulness=0.3))

    assert result.faithfulness == 0.3  # the latest override wins
    assert result.original_scores["faithfulness"] == 0.9  # but the TRUE original judge score is preserved


def test_override_evaluation_requires_admin_role(db_session):
    domain = _make_domain(db_session)
    reader_id = uuid4()
    _grant(db_session, reader_id, domain.id, DomainRole.READER)
    query_log = _make_query_log(db_session, [domain.id])
    _make_completed_evaluation(db_session, query_log.id)

    with pytest.raises(InsufficientPermissionsError):
        service.override_evaluation(db_session, domain.id, query_log.id, TokenData(user_id=str(reader_id)), _override_request())


def test_override_evaluation_rejects_archived_domain(db_session):
    from src.domains.service import archive_domain
    domain = _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain.id])
    _make_completed_evaluation(db_session, query_log.id)
    archive_domain(db_session, domain.id, uuid4())

    with pytest.raises(DomainArchivedError):
        service.override_evaluation(db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)), _override_request())


def test_override_evaluation_404s_for_wrong_domain(db_session):
    domain_a, domain_b = _make_domain(db_session), _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain_b.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain_a.id])
    _make_completed_evaluation(db_session, query_log.id)

    with pytest.raises(QueryLogNotFoundError):
        service.override_evaluation(db_session, domain_b.id, query_log.id, TokenData(user_id=str(admin_id)), _override_request())


def test_override_evaluation_creates_row_when_none_exists_yet(db_session):
    domain = _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain.id])  # no EvaluationResult row at all

    result = service.override_evaluation(db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)), _override_request())

    assert result.faithfulness == 0.2
    assert result.original_scores == {"faithfulness": None, "relevance": None, "completeness": None, "citation_accuracy": None}


def test_evaluate_query_log_skips_when_already_overridden(db_session, monkeypatch):
    domain = _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain.id])
    _make_completed_evaluation(db_session, query_log.id, faithfulness=0.9)
    service.override_evaluation(db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)), _override_request(faithfulness=0.1))

    def _boom(*a, **kw):
        raise AssertionError("must not call the judge for an already-overridden evaluation")
    monkeypatch.setattr(judge, "evaluate_answer", _boom)

    result = service.evaluate_query_log(db_session, query_log.id)

    assert result.faithfulness == 0.1  # untouched


def test_evaluate_query_log_does_not_clobber_an_override_that_lands_mid_flight(db_session, monkeypatch):
    # The most dangerous version of the race: an admin override commits
    # WHILE the (possibly multi-second) judge API call is still in
    # flight. The judge's own result must be discarded, atomically, no
    # matter how the two calls interleave -- proven here by having the
    # mocked judge call itself perform the override before returning its
    # own (now-stale) scores.
    domain = _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain.id])
    db_session.add(EvaluationResult(id=uuid4(), query_log_id=query_log.id))
    db_session.commit()

    monkeypatch.setattr(service, "get_settings", lambda: type("S", (), {
        "judge_provider": "mercury", "inception_api_key": "k", "judge_llm_enabled": False,
        "judge_api_model_name": "mercury-2.5", "judge_llm_model_name": "qwen3:4b",
    })())

    def _judge_call_that_races_an_override(*a, **kw):
        service.override_evaluation(
            db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)),
            _override_request(faithfulness=0.2, rationale="human correction mid-flight"),
        )
        return _SCORES  # the judge's own (now-stale) result -- must be discarded
    monkeypatch.setattr(judge, "evaluate_answer", _judge_call_that_races_an_override)

    result = service.evaluate_query_log(db_session, query_log.id)

    assert result.overridden_by == admin_id
    assert result.faithfulness == 0.2  # the human override's value, never _SCORES' 0.9
    assert result.override_rationale == "human correction mid-flight"


# --- set_evaluation_verdict (4.6 fix -- accept/reject, distinct from override_evaluation) ---

def _verdict_request(verdict=HumanVerdict.ACCEPTED, rationale="reviewed"):
    return models.EvaluationVerdictRequest(verdict=verdict, rationale=rationale)


def test_set_evaluation_verdict_accepts_without_changing_scores(db_session):
    domain = _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain.id])
    _make_completed_evaluation(db_session, query_log.id, faithfulness=0.9, relevance=0.9, completeness=0.9, citation_accuracy=0.9)

    result = service.set_evaluation_verdict(
        db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)),
        _verdict_request(HumanVerdict.ACCEPTED, "confirmed correct"),
    )

    assert result.human_verdict == HumanVerdict.ACCEPTED
    assert result.overridden_by == admin_id
    assert result.override_rationale == "confirmed correct"
    assert result.faithfulness == 0.9  # untouched -- verdict is orthogonal to the numeric scores
    assert result.original_scores == {"faithfulness": 0.9, "relevance": 0.9, "completeness": 0.9, "citation_accuracy": 0.9}


def test_set_evaluation_verdict_rejects_without_changing_scores(db_session):
    domain = _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain.id])
    _make_completed_evaluation(db_session, query_log.id, faithfulness=0.9)

    result = service.set_evaluation_verdict(
        db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)),
        _verdict_request(HumanVerdict.REJECTED, "answer is unusable despite the score"),
    )

    assert result.human_verdict == HumanVerdict.REJECTED
    assert result.faithfulness == 0.9  # still untouched


def test_set_evaluation_verdict_requires_admin_role(db_session):
    domain = _make_domain(db_session)
    reader_id = uuid4()
    _grant(db_session, reader_id, domain.id, DomainRole.READER)
    query_log = _make_query_log(db_session, [domain.id])
    _make_completed_evaluation(db_session, query_log.id)

    with pytest.raises(InsufficientPermissionsError):
        service.set_evaluation_verdict(db_session, domain.id, query_log.id, TokenData(user_id=str(reader_id)), _verdict_request())


def test_set_evaluation_verdict_rejects_archived_domain(db_session):
    from src.domains.service import archive_domain
    domain = _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain.id])
    _make_completed_evaluation(db_session, query_log.id)
    archive_domain(db_session, domain.id, uuid4())

    with pytest.raises(DomainArchivedError):
        service.set_evaluation_verdict(db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)), _verdict_request())


def test_set_evaluation_verdict_404s_for_wrong_domain(db_session):
    domain_a, domain_b = _make_domain(db_session), _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain_b.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain_a.id])
    _make_completed_evaluation(db_session, query_log.id)

    with pytest.raises(QueryLogNotFoundError):
        service.set_evaluation_verdict(db_session, domain_b.id, query_log.id, TokenData(user_id=str(admin_id)), _verdict_request())


def test_set_evaluation_verdict_removes_evaluation_from_moderation_queue(db_session):
    domain = _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain.id])
    evaluation = _make_completed_evaluation(db_session, query_log.id)
    evaluation.flagged = True
    db_session.commit()

    service.set_evaluation_verdict(db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)), _verdict_request(HumanVerdict.REJECTED))

    assert service.get_moderation_queue(db_session, domain.id) == []


def test_evaluate_query_log_skips_when_a_verdict_is_already_set(db_session, monkeypatch):
    # Same protection override_evaluation gets -- a verdict-only review
    # (no numeric correction) must also stop a delayed/retried judge call
    # from clobbering the human's decision.
    domain = _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain.id])
    _make_completed_evaluation(db_session, query_log.id, faithfulness=0.9)
    service.set_evaluation_verdict(db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)), _verdict_request(HumanVerdict.REJECTED))

    def _boom(*a, **kw):
        raise AssertionError("must not call the judge once a human verdict has been set")
    monkeypatch.setattr(judge, "evaluate_answer", _boom)

    result = service.evaluate_query_log(db_session, query_log.id)

    assert result.human_verdict == HumanVerdict.REJECTED  # untouched


def test_verdict_then_override_preserves_the_true_pre_review_original_scores(db_session):
    # A verdict (no score change) followed by a numeric correction --
    # original_scores must still reflect the state BEFORE either human
    # action, not get re-snapshotted at the override step.
    domain = _make_domain(db_session)
    admin_id = uuid4()
    _grant(db_session, admin_id, domain.id, DomainRole.ADMIN)
    query_log = _make_query_log(db_session, [domain.id])
    _make_completed_evaluation(db_session, query_log.id, faithfulness=0.9)

    service.set_evaluation_verdict(db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)), _verdict_request(HumanVerdict.ACCEPTED))
    result = service.override_evaluation(db_session, domain.id, query_log.id, TokenData(user_id=str(admin_id)), _override_request(faithfulness=0.3))

    assert result.faithfulness == 0.3
    assert result.original_scores["faithfulness"] == 0.9  # the true pre-review baseline, not re-snapshotted
