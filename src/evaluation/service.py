import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4
from langchain_core.documents import Document
from sqlalchemy.orm import Session
from src.entities.domain_evaluation_config import DomainEvaluationConfig
from src.entities.query_log import QueryLog
from src.entities.evaluation_result import EvaluationResult
from src.entities.golden_qa_item import GoldenQAItem
from src.entities.enums import EvaluationStatus, JudgeProvider, DomainRole
from src.auth.models import TokenData
from src.authz.service import get_effective_role
from src.config import get_settings
from src.domains.service import raise_if_archived
from src.exceptions import JudgeUnavailableError, QueryLogNotFoundError, InsufficientPermissionsError
from . import models
from . import judge


def get_or_create_evaluation_config(db: Session, domain_id: UUID) -> DomainEvaluationConfig:
    """Lazily creates a domain's evaluation config row with defaults the
    first time it's read -- mirrors chunking/service.py's
    get_or_create_ingestion_config and retrieval/service.py's
    get_or_create_retrieval_config exactly.
    """
    config = db.query(DomainEvaluationConfig).filter(DomainEvaluationConfig.domain_id == domain_id).first()
    if config:
        return config

    config = DomainEvaluationConfig(id=uuid4(), domain_id=domain_id)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_evaluation_config(
    db: Session, domain_id: UUID, update: models.DomainEvaluationConfigUpdate
) -> DomainEvaluationConfig:
    raise_if_archived(db, domain_id)

    config = get_or_create_evaluation_config(db, domain_id)
    config.flag_threshold = update.flag_threshold
    config.degradation_alert_threshold = update.degradation_alert_threshold
    config.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(config)
    logging.info(f"Evaluation config for domain {domain_id} updated")
    return config


def create_query_log(db: Session, current_user: TokenData, query: str, result: dict) -> QueryLog:
    """Spec 4.3's audit anchor -- called from retrieval/service.py::answer_query
    right after generation succeeds. `result` is answer_query's own return
    dict. Each source entry stores the chunk's own `content` (not just its
    id/score) so the async judge task below never needs a second Postgres
    read to reconstruct the context it judges -- same self-containment
    reasoning that put `graph_context` directly on this row too.
    """
    sources = [
        {
            "chunk_id": doc.metadata["chunk_id"],
            "domain_id": doc.metadata["domain_id"],
            "domain_name": doc.metadata["domain_name"],
            "content_type": doc.metadata["content_type"],
            "content": doc.page_content,
            "score": doc.metadata.get("vector_score", doc.metadata.get("graph_score")),
        }
        for doc in result["documents"]
    ]
    query_log = QueryLog(
        id=uuid4(),
        user_id=current_user.get_uuid(),
        domain_ids=[str(d) for d in result["permitted_domain_ids"]],
        query=query,
        answer=result["answer"],
        route=result["route"],
        confidence=result["confidence"],
        sources=sources,
        graph_context=result["graph_context"],
    )
    db.add(query_log)
    db.commit()
    db.refresh(query_log)
    return query_log


def _reference_for(db: Session, query_log: QueryLog) -> tuple[str, list[str]] | None:
    """4.5's stricter regression mode -- populated only when this QueryLog
    was produced by a golden-set run (Phase 5), `None` for a real user
    query (reference-free, per RAGAS's core design premise).
    """
    if not query_log.golden_qa_item_id:
        return None
    item = db.query(GoldenQAItem).filter(GoldenQAItem.id == query_log.golden_qa_item_id).first()
    if not item:
        return None
    return (item.expected_answer, item.expected_citations)


def _judge_model_version_for(provider: JudgeProvider) -> str:
    settings = get_settings()
    return settings.judge_api_model_name if provider == JudgeProvider.MERCURY else settings.judge_llm_model_name


def evaluate_query_log(db: Session, query_log_id: UUID) -> EvaluationResult:
    """4.1/4.2's actual judge call + 4.3's flagging, run from
    `pipeline.evaluate_query_log` (Celery). The task creates this row at
    `PENDING` before calling in; this function always leaves it at a
    terminal status (`COMPLETED`/`FAILED`/`SKIPPED`) -- never back at
    `PENDING` -- so a polling client is never left guessing.
    """
    query_log = db.query(QueryLog).filter(QueryLog.id == query_log_id).first()
    if query_log is None:
        raise QueryLogNotFoundError(query_log_id)

    evaluation = db.query(EvaluationResult).filter(EvaluationResult.query_log_id == query_log_id).first()
    if evaluation is None:
        # Defensive only -- the Celery task is expected to have already
        # created this row before calling in (see tasks/pipeline.py).
        evaluation = EvaluationResult(id=uuid4(), query_log_id=query_log_id)
        db.add(evaluation)
        db.commit()
        db.refresh(evaluation)

    settings = get_settings()
    provider = JudgeProvider(settings.judge_provider)

    if provider == JudgeProvider.MERCURY and not settings.inception_api_key:
        return _mark_skipped(db, evaluation, "Judge provider is 'mercury' but INCEPTION_API_KEY is not configured")
    if provider == JudgeProvider.OLLAMA and not settings.judge_llm_enabled:
        return _mark_skipped(db, evaluation, "Judge provider is 'ollama' but judge_llm_enabled is False")

    documents = [
        Document(page_content=src["content"], metadata={"chunk_id": src["chunk_id"]})
        for src in query_log.sources
    ]
    reference = _reference_for(db, query_log)

    try:
        scores = judge.evaluate_answer(
            query_log.query, documents, query_log.graph_context, query_log.answer,
            reference=reference, provider=provider,
        )
    except JudgeUnavailableError as e:
        return _mark_failed(db, evaluation, str(e.detail))

    # A query can span multiple domains, each with its own configured
    # `flag_threshold` -- use the STRICTEST (max) of them, not just the
    # first domain's. Flagging is a safety/moderation gate, not a
    # ranking-weight blend (unlike retrieve()'s own "first permitted
    # domain's tuning knobs" precedent for RRF weights): a query that
    # touched a domain with a stricter quality bar shouldn't have that
    # bar silently overridden by a laxer domain also in scope.
    flag_threshold = max(
        get_or_create_evaluation_config(db, UUID(domain_id)).flag_threshold
        for domain_id in query_log.domain_ids
    )
    dims = [scores.faithfulness, scores.relevance, scores.completeness, scores.citation_accuracy]

    evaluation.status = EvaluationStatus.COMPLETED
    evaluation.faithfulness = scores.faithfulness
    evaluation.relevance = scores.relevance
    evaluation.completeness = scores.completeness
    evaluation.citation_accuracy = scores.citation_accuracy
    evaluation.rationale = {
        "faithfulness": scores.faithfulness_rationale,
        "relevance": scores.relevance_rationale,
        "completeness": scores.completeness_rationale,
        "citation_accuracy": scores.citation_accuracy_rationale,
    }
    evaluation.flagged = any(d < flag_threshold for d in dims)  # 4.3: "below threshold on any dimension"
    evaluation.judge_provider = provider
    evaluation.judge_model_version = _judge_model_version_for(provider)
    evaluation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(evaluation)
    logging.info(f"Evaluation {evaluation.id} for query_log {query_log_id} completed, flagged={evaluation.flagged}")
    return evaluation


def _mark_skipped(db: Session, evaluation: EvaluationResult, reason: str) -> EvaluationResult:
    evaluation.status = EvaluationStatus.SKIPPED
    evaluation.error_message = reason
    evaluation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(evaluation)
    return evaluation


def _mark_failed(db: Session, evaluation: EvaluationResult, reason: str) -> EvaluationResult:
    evaluation.status = EvaluationStatus.FAILED
    evaluation.error_message = reason
    evaluation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(evaluation)
    return evaluation


def _can_view_query_log(db: Session, user_id: UUID, query_log: QueryLog) -> bool:
    if user_id == query_log.user_id:
        return True
    return any(
        get_effective_role(db, user_id, UUID(domain_id)) == DomainRole.ADMIN
        for domain_id in query_log.domain_ids
    )


def get_evaluation(db: Session, current_user: TokenData, query_log_id: UUID) -> EvaluationResult | None:
    """4.3's polling endpoint -- returns `None` when the judge task hasn't
    created its row yet (the controller renders that as a `PENDING`
    response), or the real row otherwise. Visible only to the user who
    issued the query or a domain admin of one of its domains.
    """
    query_log = db.query(QueryLog).filter(QueryLog.id == query_log_id).first()
    if query_log is None:
        raise QueryLogNotFoundError(query_log_id)

    if not _can_view_query_log(db, current_user.get_uuid(), query_log):
        raise InsufficientPermissionsError()

    return db.query(EvaluationResult).filter(EvaluationResult.query_log_id == query_log_id).first()


def get_moderation_queue(db: Session, domain_id: UUID) -> list[EvaluationResult]:
    """4.3's "moderation queue for admin review" -- flagged, not-yet-
    overridden evaluations for one domain. Filters `QueryLog.domain_ids`
    (a JSON list) in Python rather than a DB-specific JSON-containment
    operator, so this works identically against sqlite (tests) and
    Postgres (prod) -- fine at MVP scale, same documented tradeoff as
    bm25_retriever.py's in-memory rebuild.
    """
    domain_id_str = str(domain_id)
    rows = (
        db.query(EvaluationResult, QueryLog.domain_ids)
        .join(QueryLog, EvaluationResult.query_log_id == QueryLog.id)
        .filter(EvaluationResult.flagged.is_(True), EvaluationResult.overridden_by.is_(None))
        .all()
    )
    return [result for result, domain_ids in rows if domain_id_str in domain_ids]
