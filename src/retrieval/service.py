import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from src.entities.domain_retrieval_config import DomainRetrievalConfig
from src.exceptions import InvalidRetrievalConfigError
from src.auth.models import TokenData
from src.authz.retrieval import build_retrieval_filter
from src.domains.service import raise_if_archived
from . import models

RETRIEVAL_TOP_K = 5


def get_or_create_retrieval_config(db: Session, domain_id: UUID) -> DomainRetrievalConfig:
    """Lazily creates a domain's retrieval config row with defaults the
    first time it's read, rather than at domain-creation time -- a
    domain that never queries never needs one. Mirrors
    chunking/service.py's get_or_create_ingestion_config exactly.
    """
    config = db.query(DomainRetrievalConfig).filter(DomainRetrievalConfig.domain_id == domain_id).first()
    if config:
        return config

    config = DomainRetrievalConfig(id=uuid4(), domain_id=domain_id)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_retrieval_config(
    db: Session, domain_id: UUID, update: models.DomainRetrievalConfigUpdate
) -> DomainRetrievalConfig:
    raise_if_archived(db, domain_id)
    if update.dense_weight == 0 and update.bm25_weight == 0 and update.graph_weight == 0:
        raise InvalidRetrievalConfigError("at least one of dense_weight/bm25_weight/graph_weight must be > 0")

    config = get_or_create_retrieval_config(db, domain_id)
    config.dense_weight = update.dense_weight
    config.bm25_weight = update.bm25_weight
    config.graph_weight = update.graph_weight
    config.entity_centric_ratio_threshold = update.entity_centric_ratio_threshold
    config.entity_centric_graph_boost = update.entity_centric_graph_boost
    config.llm_routing_default = update.llm_routing_default
    config.llm_routing_sensitive_keywords = update.llm_routing_sensitive_keywords
    config.confidence_threshold = update.confidence_threshold
    config.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(config)
    logging.info(f"Retrieval config for domain {domain_id} updated")
    return config


def retrieve(db: Session, current_user: TokenData, query: str, requested_domain_ids: list[UUID]) -> dict:
    
    retrieval_filter = build_retrieval_filter(db, current_user, requested_domain_ids)
    return _retrieve_for_permitted_domains(db, query, retrieval_filter.permitted_domain_ids)


def _retrieve_for_permitted_domains(db: Session, query: str, permitted: list[UUID]) -> dict:
    
    from langchain_classic.retrievers.ensemble import EnsembleRetriever
    from .ner import analyze_query
    from .graph_retriever import Neo4jGraphChunkRetriever
    from . import router

    # Multi-domain query: use the first permitted domain's tuning knobs
    # (per-query cross-domain weight merging is out of scope for MVP).
    config = get_or_create_retrieval_config(db, permitted[0])

    entities, entity_token_ratio = analyze_query(query)
    retrievers, weights = router.select_retrievers_and_weights(
        db, entities, entity_token_ratio, permitted, config, k=RETRIEVAL_TOP_K
    )

    
    doc_lists = [r.invoke(query) for r in retrievers]
    ensemble = EnsembleRetriever(retrievers=retrievers, weights=weights, id_key="chunk_id")
    documents = ensemble.weighted_reciprocal_rank(doc_lists)[:RETRIEVAL_TOP_K]

    graph_context: list[str] = []
    if entities:
        graph_docs = next(
            docs for r, docs in zip(retrievers, doc_lists) if isinstance(r, Neo4jGraphChunkRetriever)
        )
        graph_scores = {d.metadata["chunk_id"]: d.metadata["graph_score"] for d in graph_docs}
        for d in documents:
            if d.metadata["chunk_id"] in graph_scores:
                d.metadata.setdefault("graph_score", graph_scores[d.metadata["chunk_id"]])
        
        graph_context = sorted({triple for d in graph_docs for triple in d.metadata.get("graph_triples", [])})

    confidence = router.compute_confidence(documents, graph_activated=bool(entities))
    return {
        "query": query,
        "permitted_domain_ids": permitted,
        "entities": entities,
        "documents": documents,
        "graph_context": graph_context,
        "confidence": confidence,
        "low_confidence": confidence < config.confidence_threshold,
        "config": config,
    }


def answer_query(db: Session, current_user: TokenData, query: str, requested_domain_ids: list[UUID]) -> dict:
    """3.5's orchestration: retrieve() covers 3.1-3.4/3.6, this adds
    generation on top and returns the full /query payload. Spec 4.1's
    judge is dispatched here too, right after the QueryLog commit --
    fire-and-forget, so it never adds to this response's latency.
    """
    from src.generation.service import generate_answer
    from src.evaluation.service import create_query_log

    result = retrieve(db, current_user, query, requested_domain_ids)
    answer, route = generate_answer(query, result["documents"], result["config"])
    result["answer"] = answer
    result["route"] = route

    query_log = create_query_log(db, current_user, query, result)
    result["query_log_id"] = query_log.id
    _enqueue_evaluation(query_log.id)

    return result


def _enqueue_evaluation(query_log_id: UUID) -> None:
    # Imported lazily to avoid a retrieval<->tasks import cycle, same
    # rationale as chunking/service.py's _enqueue_reindex.
    from src.tasks.pipeline import evaluate_query_log_task
    evaluate_query_log_task.delay(str(query_log_id))
