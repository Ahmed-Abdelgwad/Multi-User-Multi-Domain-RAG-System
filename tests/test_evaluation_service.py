import pytest
from uuid import uuid4
from langchain_core.documents import Document
from src.entities.domain import Domain
from src.entities.user_domain_role import UserDomainRole
from src.entities.query_log import QueryLog
from src.entities.evaluation_result import EvaluationResult
from src.entities.enums import DomainRole, LLMRoute, JudgeProvider, EvaluationStatus
from src.auth.models import TokenData
from src.exceptions import InsufficientPermissionsError, JudgeUnavailableError
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
