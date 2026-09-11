from uuid import uuid4
import pytest
from langchain_core.documents import Document
from src.retrieval import router
from src.retrieval.vector_retriever import PgVectorChunkRetriever
from src.retrieval.graph_retriever import Neo4jGraphChunkRetriever


class _Config:
    dense_weight = 1.0
    bm25_weight = 0.5
    graph_weight = 2.0


class _FakeBM25:
    pass


def _doc(**meta):
    return Document(page_content="x", metadata=meta)


# --- compute_confidence ---

def test_compute_confidence_vector_only_averages_vector_scores():
    docs = [_doc(vector_score=0.8), _doc(vector_score=0.6), _doc()]
    assert router.compute_confidence(docs, graph_activated=False) == 0.7


def test_compute_confidence_blends_graph_50_50_when_activated():
    docs = [_doc(vector_score=0.8), _doc(graph_score=0.4)]
    # vec avg = 0.8, graph avg = 0.4 -> 0.5*0.8 + 0.5*0.4 = 0.6
    assert router.compute_confidence(docs, graph_activated=True) == pytest.approx(0.6)


def test_compute_confidence_empty_is_zero_and_clamps():
    assert router.compute_confidence([], graph_activated=False) == 0.0
    assert router.compute_confidence([_doc(vector_score=5.0)], graph_activated=False) == 1.0


# --- select_retrievers_and_weights ---

def test_select_no_entities_omits_graph(db_session, monkeypatch):
    monkeypatch.setattr(router, "get_bm25_retriever", lambda *a, **k: _FakeBM25())
    retrievers, weights = router.select_retrievers_and_weights(
        db_session, entities=[], entity_token_ratio=0.0,
        permitted_domain_ids=[uuid4()], config=_Config(),
    )
    assert isinstance(retrievers[0], PgVectorChunkRetriever)
    assert not any(isinstance(r, Neo4jGraphChunkRetriever) for r in retrievers)
    assert weights == [1.0, 0.5]


def test_select_entities_low_ratio_adds_graph_at_configured_weight(db_session, monkeypatch):
    monkeypatch.setattr(router, "get_bm25_retriever", lambda *a, **k: _FakeBM25())
    retrievers, weights = router.select_retrievers_and_weights(
        db_session, entities=[("Acme", "ORG")], entity_token_ratio=0.1,
        permitted_domain_ids=[uuid4()], config=_Config(),
    )
    assert isinstance(retrievers[-1], Neo4jGraphChunkRetriever)
    assert weights == [1.0, 0.5, 2.0]


def test_select_entities_high_ratio_boosts_graph_weight(db_session, monkeypatch):
    monkeypatch.setattr(router, "get_bm25_retriever", lambda *a, **k: _FakeBM25())
    _retrievers, weights = router.select_retrievers_and_weights(
        db_session, entities=[("Acme", "ORG")], entity_token_ratio=0.9,
        permitted_domain_ids=[uuid4()], config=_Config(),
    )
    assert weights == [1.0, 0.5, 2.0 * router.ENTITY_CENTRIC_GRAPH_BOOST]


def test_select_skips_bm25_when_none(db_session, monkeypatch):
    monkeypatch.setattr(router, "get_bm25_retriever", lambda *a, **k: None)
    retrievers, weights = router.select_retrievers_and_weights(
        db_session, entities=[], entity_token_ratio=0.0,
        permitted_domain_ids=[uuid4()], config=_Config(),
    )
    assert len(retrievers) == 1
    assert weights == [1.0]
