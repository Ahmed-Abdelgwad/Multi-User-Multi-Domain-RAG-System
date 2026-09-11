from uuid import uuid4
import pytest
from src.entities.domain import Domain
from src.entities.enums import LLMRoute
from src.exceptions import InvalidRetrievalConfigError
from src.retrieval import service, models


def _make_domain(db_session) -> Domain:
    domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4())
    db_session.add(domain)
    db_session.commit()
    return domain


def test_get_or_create_retrieval_config_creates_defaults(db_session):
    domain = _make_domain(db_session)

    config = service.get_or_create_retrieval_config(db_session, domain.id)

    assert config.domain_id == domain.id
    assert config.dense_weight == 1.0
    assert config.bm25_weight == 1.0
    assert config.graph_weight == 1.0
    assert config.entity_centric_ratio_threshold == 0.3
    assert config.entity_centric_graph_boost == 2.0
    assert config.llm_routing_default == LLMRoute.API
    assert config.llm_routing_sensitive_keywords == []
    assert config.confidence_threshold == 0.5


def test_get_or_create_retrieval_config_is_idempotent(db_session):
    domain = _make_domain(db_session)

    first = service.get_or_create_retrieval_config(db_session, domain.id)
    second = service.get_or_create_retrieval_config(db_session, domain.id)

    assert first.id == second.id


def test_update_retrieval_config_persists_new_values(db_session):
    domain = _make_domain(db_session)

    config = service.update_retrieval_config(
        db_session, domain.id,
        models.DomainRetrievalConfigUpdate(
            dense_weight=0.5, bm25_weight=0.5, graph_weight=2.0,
            entity_centric_ratio_threshold=0.6, entity_centric_graph_boost=3.0,
            llm_routing_default=LLMRoute.LOCAL,
            llm_routing_sensitive_keywords=["confidential"],
            confidence_threshold=0.8,
        ),
    )

    assert config.dense_weight == 0.5
    assert config.graph_weight == 2.0
    assert config.entity_centric_ratio_threshold == 0.6
    assert config.entity_centric_graph_boost == 3.0
    assert config.llm_routing_default == LLMRoute.LOCAL
    assert config.llm_routing_sensitive_keywords == ["confidential"]
    assert config.confidence_threshold == 0.8


def test_update_retrieval_config_rejects_all_zero_weights(db_session):
    domain = _make_domain(db_session)

    with pytest.raises(InvalidRetrievalConfigError):
        service.update_retrieval_config(
            db_session, domain.id,
            models.DomainRetrievalConfigUpdate(
                dense_weight=0, bm25_weight=0, graph_weight=0,
                entity_centric_ratio_threshold=0.3, entity_centric_graph_boost=2.0,
                llm_routing_default=LLMRoute.API,
                confidence_threshold=0.5,
            ),
        )
