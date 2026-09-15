import csv
import io
import logging
from datetime import datetime, timedelta, timezone
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
from src.exceptions import (
    JudgeUnavailableError, QueryLogNotFoundError, InsufficientPermissionsError, InvalidDashboardWindowError,
    GoldenQAItemNotFoundError,
)
from . import models
from . import judge


def get_or_create_evaluation_config(db: Session, domain_id: UUID) -> DomainEvaluationConfig:
    
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


def create_query_log(
    db: Session, current_user: TokenData, query: str, result: dict, golden_qa_item_id: UUID | None = None,
) -> QueryLog:
    
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
        golden_qa_item_id=golden_qa_item_id,
    )
    db.add(query_log)
    db.commit()
    db.refresh(query_log)
    return query_log


def _reference_for(db: Session, query_log: QueryLog) -> tuple[str, list[str]] | None:

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
    
    query_log = db.query(QueryLog).filter(QueryLog.id == query_log_id).first()
    if query_log is None:
        raise QueryLogNotFoundError(query_log_id)

    evaluation = db.query(EvaluationResult).filter(EvaluationResult.query_log_id == query_log_id).first()
    if evaluation is None:

        evaluation = EvaluationResult(id=uuid4(), query_log_id=query_log_id)
        db.add(evaluation)
        db.commit()
        db.refresh(evaluation)

    if evaluation.overridden_by is not None:
        # 4.6: a human override is terminal. Without this guard, a
        # delayed/retried Celery run (e.g. a slow API call that only
        # completes after an admin has already reviewed and corrected
        # this evaluation) would silently clobber the human's scores
        # with a fresh judge call the admin never asked for.
        return evaluation

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


    flag_threshold = max(
        get_or_create_evaluation_config(db, UUID(domain_id)).flag_threshold
        for domain_id in query_log.domain_ids
    )
    dims = [scores.faithfulness, scores.relevance, scores.completeness, scores.citation_accuracy]

    return _finalize_evaluation(db, evaluation, {
        EvaluationResult.status: EvaluationStatus.COMPLETED,
        EvaluationResult.faithfulness: scores.faithfulness,
        EvaluationResult.relevance: scores.relevance,
        EvaluationResult.completeness: scores.completeness,
        EvaluationResult.citation_accuracy: scores.citation_accuracy,
        EvaluationResult.rationale: {
            "faithfulness": scores.faithfulness_rationale,
            "relevance": scores.relevance_rationale,
            "completeness": scores.completeness_rationale,
            "citation_accuracy": scores.citation_accuracy_rationale,
        },
        EvaluationResult.flagged: any(d < flag_threshold for d in dims),  # 4.3: below threshold on any dimension
        EvaluationResult.judge_provider: provider,
        EvaluationResult.judge_model_version: _judge_model_version_for(provider),
    })


def _finalize_evaluation(db: Session, evaluation: EvaluationResult, updates: dict) -> EvaluationResult:
    """Writes a judge result (COMPLETED/SKIPPED/FAILED) via a conditional
    UPDATE guarded on overridden_by IS NULL -- atomic at the database
    level. The early `overridden_by is not None` check above only
    catches an override that landed *before* the (possibly multi-second)
    judge API call started; this closes the real race: an override that
    lands *while* that call is in flight must still never be clobbered
    by the judge result that finishes after it, no matter how the two
    interleave in wall-clock time.
    """
    updates = {**updates, EvaluationResult.updated_at: datetime.now(timezone.utc)}
    changed = (
        db.query(EvaluationResult)
        .filter(EvaluationResult.id == evaluation.id, EvaluationResult.overridden_by.is_(None))
        .update(updates)
    )
    db.commit()
    db.refresh(evaluation)
    if changed == 0:
        logging.info(f"Evaluation {evaluation.id} was overridden mid-flight -- discarding this judge result")
    return evaluation


def _mark_skipped(db: Session, evaluation: EvaluationResult, reason: str) -> EvaluationResult:
    return _finalize_evaluation(db, evaluation, {
        EvaluationResult.status: EvaluationStatus.SKIPPED, EvaluationResult.error_message: reason,
    })


def _mark_failed(db: Session, evaluation: EvaluationResult, reason: str) -> EvaluationResult:
    return _finalize_evaluation(db, evaluation, {
        EvaluationResult.status: EvaluationStatus.FAILED, EvaluationResult.error_message: reason,
    })


def _can_view_query_log(db: Session, user_id: UUID, query_log: QueryLog) -> bool:
    if user_id == query_log.user_id:
        return True
    return any(
        get_effective_role(db, user_id, UUID(domain_id)) == DomainRole.ADMIN
        for domain_id in query_log.domain_ids
    )


def get_evaluation(db: Session, current_user: TokenData, query_log_id: UUID) -> EvaluationResult | None:
    
    query_log = db.query(QueryLog).filter(QueryLog.id == query_log_id).first()
    if query_log is None:
        raise QueryLogNotFoundError(query_log_id)

    if not _can_view_query_log(db, current_user.get_uuid(), query_log):
        raise InsufficientPermissionsError()

    return db.query(EvaluationResult).filter(EvaluationResult.query_log_id == query_log_id).first()


def get_moderation_queue(db: Session, domain_id: UUID) -> list[EvaluationResult]:
    
    domain_id_str = str(domain_id)
    rows = (
        db.query(EvaluationResult, QueryLog.domain_ids)
        .join(QueryLog, EvaluationResult.query_log_id == QueryLog.id)
        .filter(EvaluationResult.flagged.is_(True), EvaluationResult.overridden_by.is_(None))
        .all()
    )
    return [result for result, domain_ids in rows if domain_id_str in domain_ids]


def _authorize_and_load_evaluation_for_review(
    db: Session, domain_id: UUID, query_log_id: UUID, current_user: TokenData,
) -> tuple[EvaluationResult, UUID]:
    """Shared setup for every 4.6 human-review action (numeric override,
    accept/reject verdict): the controller's own `RequireDomainAdmin`
    dependency already gates the endpoint on `domain_id`, but the
    admin-role check is re-verified here too since these mutate
    historical judge data used for calibration -- deliberate
    defense-in-depth rather than trusting the controller wiring alone.
    Checked before the archived-domain check (same ordering as
    authz/retrieval.py::build_retrieval_filter, for the same reason: an
    unauthorized caller must never learn a domain's archived status
    before their own permission is confirmed).
    """
    admin_id = current_user.get_uuid()
    if get_effective_role(db, admin_id, domain_id) != DomainRole.ADMIN:
        raise InsufficientPermissionsError(domain_ids=[domain_id], required_role=DomainRole.ADMIN)
    raise_if_archived(db, domain_id)

    query_log = db.query(QueryLog).filter(QueryLog.id == query_log_id).first()
    if query_log is None or str(domain_id) not in query_log.domain_ids:
        raise QueryLogNotFoundError(query_log_id)

    evaluation = db.query(EvaluationResult).filter(EvaluationResult.query_log_id == query_log_id).first()
    if evaluation is None:
        evaluation = EvaluationResult(id=uuid4(), query_log_id=query_log_id)
        db.add(evaluation)
        db.commit()
        db.refresh(evaluation)

    return evaluation, admin_id


def _snapshot_original_scores_once(evaluation: EvaluationResult) -> None:
    """Snapshot the pre-review scores only on the FIRST human touch
    (override or verdict) -- a later action must not overwrite the true
    original judge call with an already-touched value, or 4.6's stated
    "calibrate judge thresholds over time" use case loses its actual
    baseline after a second edit.
    """
    if evaluation.overridden_by is None:
        evaluation.original_scores = {
            "faithfulness": evaluation.faithfulness,
            "relevance": evaluation.relevance,
            "completeness": evaluation.completeness,
            "citation_accuracy": evaluation.citation_accuracy,
        }


def override_evaluation(
    db: Session, domain_id: UUID, query_log_id: UUID, current_user: TokenData,
    override: models.EvaluationOverrideRequest,
) -> EvaluationResult:
    """4.6's numeric score correction -- logged only for this MVP (no
    judge fine-tuning from override data).
    """
    evaluation, admin_id = _authorize_and_load_evaluation_for_review(db, domain_id, query_log_id, current_user)
    _snapshot_original_scores_once(evaluation)

    evaluation.faithfulness = override.faithfulness
    evaluation.relevance = override.relevance
    evaluation.completeness = override.completeness
    evaluation.citation_accuracy = override.citation_accuracy
    evaluation.status = EvaluationStatus.COMPLETED
    evaluation.overridden_by = admin_id
    evaluation.override_rationale = override.rationale
    evaluation.overridden_at = datetime.now(timezone.utc)
    evaluation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(evaluation)
    logging.info(f"Evaluation {evaluation.id} for query_log {query_log_id} overridden by {admin_id}")
    return evaluation


def set_evaluation_verdict(
    db: Session, domain_id: UUID, query_log_id: UUID, current_user: TokenData,
    verdict: models.EvaluationVerdictRequest,
) -> EvaluationResult:
    """4.6's "accept or reject flagged answers" -- a moderation verdict
    on the answer's overall usability, independent of (and combinable
    with) override_evaluation's numeric score correction: an admin can
    reject an answer for reasons the four judge dimensions don't fully
    capture, or accept one as-is to confirm the judge scored it
    correctly. Deliberately does not touch the four score fields.
    """
    evaluation, admin_id = _authorize_and_load_evaluation_for_review(db, domain_id, query_log_id, current_user)
    _snapshot_original_scores_once(evaluation)

    evaluation.human_verdict = verdict.verdict
    evaluation.overridden_by = admin_id
    evaluation.override_rationale = verdict.rationale
    evaluation.overridden_at = datetime.now(timezone.utc)
    evaluation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(evaluation)
    logging.info(f"Evaluation {evaluation.id} for query_log {query_log_id} marked {verdict.verdict.value} by {admin_id}")
    return evaluation


DIMENSIONS = ("faithfulness", "relevance", "completeness", "citation_accuracy")
MAX_DASHBOARD_WINDOW_DAYS = 365
MAX_TREND_POINTS = 24

MIN_DEGRADATION_SAMPLE_COUNT = 3


def _dimension_stats(rows: list[EvaluationResult]) -> dict[str, models.QualityDashboardDimension]:
    stats = {}
    for dim in DIMENSIONS:
        values = [v for r in rows if (v := getattr(r, dim)) is not None]
        mean = sum(values) / len(values) if values else None
        stats[dim] = models.QualityDashboardDimension(mean=mean, sample_count=len(values))
    return stats


def _completed_evaluations_in_window(
    db: Session, domain_id: UUID, window_start: datetime, window_end: datetime
) -> list[tuple[EvaluationResult, str]]:
    # Excludes golden-regression traffic (QueryLog.golden_qa_item_id IS
    # NOT NULL) -- those numbers are surfaced separately via
    # get_golden_regression_summary below, so they never silently skew
    # what a domain admin sees as real, live user-facing quality.
    domain_id_str = str(domain_id)
    rows = (
        db.query(EvaluationResult, QueryLog.domain_ids, QueryLog.route)
        .join(QueryLog, EvaluationResult.query_log_id == QueryLog.id)
        .filter(
            EvaluationResult.status == EvaluationStatus.COMPLETED,
            EvaluationResult.updated_at >= window_start,
            EvaluationResult.updated_at < window_end,
            QueryLog.golden_qa_item_id.is_(None),
        )
        .all()
    )
    return [(result, route.value) for result, domain_ids, route in rows if domain_id_str in domain_ids]


def _latest_regression_evaluations(db: Session, domain_id: UUID) -> list[EvaluationResult]:
    """One row per golden item -- its most recently-run evaluation,
    regardless of which nightly batch produced it. This is what "the
    golden set's current state" means when regression isn't tracked as
    discrete numbered runs (see run_golden_regression_for_domain).
    """
    domain_id_str = str(domain_id)
    rows = (
        db.query(EvaluationResult, QueryLog)
        .join(QueryLog, EvaluationResult.query_log_id == QueryLog.id)
        .filter(QueryLog.golden_qa_item_id.isnot(None), EvaluationResult.status == EvaluationStatus.COMPLETED)
        .all()
    )
    latest_by_item: dict[UUID, tuple[EvaluationResult, QueryLog]] = {}
    for evaluation, query_log in rows:
        if domain_id_str not in query_log.domain_ids:
            continue
        item_id = query_log.golden_qa_item_id
        existing = latest_by_item.get(item_id)
        if existing is None or query_log.created_at > existing[1].created_at:
            latest_by_item[item_id] = (evaluation, query_log)
    return [evaluation for evaluation, _ in latest_by_item.values()]


def get_golden_regression_summary(db: Session, domain_id: UUID) -> models.GoldenRegressionSummary:
    """Spec 4.5's "results surfaced in the quality dashboard" -- folded
    into get_quality_dashboard below as its own field, never mixed into
    the live-traffic aggregates.
    """
    evaluations = _latest_regression_evaluations(db, domain_id)
    return models.GoldenRegressionSummary(
        item_count=len(evaluations),
        flagged_count=sum(1 for e in evaluations if e.flagged),
        last_run_at=max((e.updated_at for e in evaluations), default=None),
        by_dimension=_dimension_stats(evaluations),
    )


def get_quality_dashboard(
    db: Session, domain_id: UUID, window_days: int = 30, trend_points: int = 6,
) -> models.QualityDashboardResponse:
    """4.4's dashboard. `by_dimension`/`by_route`/`degrading_dimensions`
    are the current-vs-previous-window snapshot (unchanged shape from
    before); `trend` is the real "trended over time" signal spec 4.4
    literally asks for -- `trend_points` consecutive `window_days`-wide
    buckets, oldest first, so a client can chart it directly. `trend[-1]`
    and `trend[-2]` are exactly the same two windows `by_dimension`/the
    degradation check already use -- computing the trend doesn't change
    either of those, it just also exposes every earlier bucket.
    """
    if not (0 < window_days <= MAX_DASHBOARD_WINDOW_DAYS):
        raise InvalidDashboardWindowError(f"window_days must be between 1 and {MAX_DASHBOARD_WINDOW_DAYS}")
    if not (0 < trend_points <= MAX_TREND_POINTS):
        raise InvalidDashboardWindowError(f"trend_points must be between 1 and {MAX_TREND_POINTS}")

    now = datetime.now(timezone.utc)
    # bucket_bounds[0] is the most recent (current) window, [1] the one
    # before it, etc. -- matches the old current_start/previous_start
    # pair exactly when trend_points >= 2.
    bucket_bounds = [
        (now - timedelta(days=window_days * (i + 1)), now - timedelta(days=window_days * i))
        for i in range(trend_points)
    ]
    buckets = [_completed_evaluations_in_window(db, domain_id, start, end) for start, end in bucket_bounds]

    current = buckets[0]
    by_dimension = _dimension_stats([result for result, _ in current])

    by_route: dict[str, dict[str, models.QualityDashboardDimension]] = {}
    for route in {route for _, route in current}:
        by_route[route] = _dimension_stats([result for result, rt in current if rt == route])

    previous_by_dimension = _dimension_stats([result for result, _ in buckets[1]]) if len(buckets) > 1 else _dimension_stats([])
    config = get_or_create_evaluation_config(db, domain_id)
    degrading = [
        dim
        for dim in DIMENSIONS
        if by_dimension[dim].mean is not None
        and previous_by_dimension[dim].mean is not None
        and by_dimension[dim].sample_count >= MIN_DEGRADATION_SAMPLE_COUNT
        and previous_by_dimension[dim].sample_count >= MIN_DEGRADATION_SAMPLE_COUNT
        and (previous_by_dimension[dim].mean - by_dimension[dim].mean) > config.degradation_alert_threshold
    ]

    trend = [
        models.QualityDashboardTrendPoint(
            period_start=start, period_end=end,
            by_dimension=_dimension_stats([result for result, _ in bucket]),
        )
        for (start, end), bucket in reversed(list(zip(bucket_bounds, buckets)))
    ]

    return models.QualityDashboardResponse(
        domain_id=domain_id, window_days=window_days,
        by_dimension=by_dimension, by_route=by_route, degrading_dimensions=degrading,
        trend=trend, golden_regression=get_golden_regression_summary(db, domain_id),
    )


def create_golden_qa_item(
    db: Session, domain_id: UUID, current_user: TokenData, item: models.GoldenQAItemCreate,
) -> GoldenQAItem:
    raise_if_archived(db, domain_id)
    row = GoldenQAItem(
        id=uuid4(), domain_id=domain_id, question=item.question,
        expected_answer=item.expected_answer, expected_citations=item.expected_citations,
        created_by=current_user.get_uuid(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_golden_qa_items(db: Session, domain_id: UUID) -> list[GoldenQAItem]:
    return (
        db.query(GoldenQAItem)
        .filter(GoldenQAItem.domain_id == domain_id)
        .order_by(GoldenQAItem.created_at)
        .all()
    )


def _get_golden_qa_item_or_404(db: Session, domain_id: UUID, item_id: UUID) -> GoldenQAItem:
    # Scoped to domain_id, not just item_id -- same domain-scoped-404
    # pattern used elsewhere in this project, so an item id from one
    # domain can't be probed for existence through another domain's path.
    item = db.query(GoldenQAItem).filter(
        GoldenQAItem.id == item_id, GoldenQAItem.domain_id == domain_id,
    ).first()
    if item is None:
        raise GoldenQAItemNotFoundError(item_id)
    return item


def get_golden_qa_item(db: Session, domain_id: UUID, item_id: UUID) -> GoldenQAItem:
    return _get_golden_qa_item_or_404(db, domain_id, item_id)


def update_golden_qa_item(
    db: Session, domain_id: UUID, item_id: UUID, update: models.GoldenQAItemCreate,
) -> GoldenQAItem:
    raise_if_archived(db, domain_id)
    item = _get_golden_qa_item_or_404(db, domain_id, item_id)
    item.question = update.question
    item.expected_answer = update.expected_answer
    item.expected_citations = update.expected_citations
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return item


def delete_golden_qa_item(db: Session, domain_id: UUID, item_id: UUID) -> None:
    raise_if_archived(db, domain_id)
    item = _get_golden_qa_item_or_404(db, domain_id, item_id)
    db.delete(item)
    db.commit()


def run_golden_regression_for_domain(db: Session, domain_id: UUID) -> list[QueryLog]:
    
    from src.retrieval.service import _retrieve_for_permitted_domains
    from src.generation.service import generate_answer

    raise_if_archived(db, domain_id)

    query_logs = []
    for item in list_golden_qa_items(db, domain_id):
        try:
            result = _retrieve_for_permitted_domains(db, item.question, [domain_id])
            answer, route = generate_answer(item.question, result["documents"], result["config"])
            result["answer"] = answer
            result["route"] = route

            actor = TokenData(user_id=str(item.created_by))
            query_log = create_query_log(db, actor, item.question, result, golden_qa_item_id=item.id)
            evaluate_query_log(db, query_log.id)
            query_logs.append(query_log)
        except Exception:
            logging.exception(f"Golden regression failed for item {item.id} in domain {domain_id}")
    return query_logs


def enqueue_golden_regression(domain_id: UUID) -> None:
    """Fire-and-forget trigger for one domain's golden regression run --
    same lazy-import-to-avoid-a-cycle shape as chunking/service.py's
    _enqueue_reindex and ontology/service.py's _enqueue_reextraction.
    """
    from src.tasks.pipeline import run_golden_regression_for_domain_task
    run_golden_regression_for_domain_task.delay(str(domain_id))


def trigger_golden_regression(db: Session, domain_id: UUID) -> None:
    """The manual `POST .../run-regression` endpoint's service call --
    unlike `_enqueue_reindex`/`_enqueue_reextraction` (only ever reached
    from a config-mutation call site that already ran raise_if_archived
    first), this is a bare, dedicated trigger with no prior write to gate
    through, so the archived check has to happen here instead. Without
    it, an archived domain's regression would still return 202 and only
    fail invisibly inside the Celery task (run_golden_regression_for_domain
    also calls raise_if_archived, but by then there's no caller left to
    see it). The nightly sweep (`pipeline.run_golden_regression`) fans
    out straight to the Celery task instead of through this function --
    the per-domain task's own raise_if_archived is enough to skip an
    archived domain there, since nightly runs have no HTTP caller waiting
    on an immediate error anyway.
    """
    raise_if_archived(db, domain_id)
    enqueue_golden_regression(domain_id)


def export_quality_dashboard_csv(
    db: Session, domain_id: UUID, window_days: int = 30, trend_points: int = 6,
) -> str:
    """4.4's CSV export -- same dashboard data, flattened to rows, plus
    the trend series and golden-regression summary as their own
    clearly-separated sections.
    """
    dashboard = get_quality_dashboard(db, domain_id, window_days, trend_points)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["route", "dimension", "mean", "sample_count"])
    for dim, stats in dashboard.by_dimension.items():
        writer.writerow(["all", dim, stats.mean, stats.sample_count])
    for route, dims in dashboard.by_route.items():
        for dim, stats in dims.items():
            writer.writerow([route, dim, stats.mean, stats.sample_count])
    for dim in DIMENSIONS:
        writer.writerow(["degrading" if dim in dashboard.degrading_dimensions else "stable", dim, "", ""])

    writer.writerow([])
    writer.writerow(["period_start", "period_end", "dimension", "mean", "sample_count"])
    for point in dashboard.trend:
        for dim, stats in point.by_dimension.items():
            writer.writerow([point.period_start.isoformat(), point.period_end.isoformat(), dim, stats.mean, stats.sample_count])

    writer.writerow([])
    writer.writerow(["golden_regression_item_count", dashboard.golden_regression.item_count])
    writer.writerow(["golden_regression_flagged_count", dashboard.golden_regression.flagged_count])
    writer.writerow([
        "golden_regression_last_run_at",
        dashboard.golden_regression.last_run_at.isoformat() if dashboard.golden_regression.last_run_at else "",
    ])
    for dim, stats in dashboard.golden_regression.by_dimension.items():
        writer.writerow(["golden_regression", dim, stats.mean, stats.sample_count])
    return buffer.getvalue()
