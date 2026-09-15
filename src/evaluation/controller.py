from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Response, status
from src.database.core import DbSession
from src.entities.enums import DomainRole, EvaluationStatus
from src.authz.dependencies import RequireDomainAdmin
from src.auth.service import CurrentUser
from . import models
from . import service

evaluation_config_router = APIRouter(
    prefix="/domains/{domain_id}/evaluation-config",
    tags=["Evaluation Config"],
)

query_evaluation_router = APIRouter(prefix="/query", tags=["Query Evaluation"])

moderation_queue_router = APIRouter(
    prefix="/domains/{domain_id}/moderation-queue",
    tags=["Moderation Queue"],
)

quality_dashboard_router = APIRouter(
    prefix="/domains/{domain_id}/quality-dashboard",
    tags=["Quality Dashboard"],
)

golden_qa_router = APIRouter(
    prefix="/domains/{domain_id}/golden-qa",
    tags=["Golden QA"],
)


@evaluation_config_router.get("/", response_model=models.DomainEvaluationConfigResponse)
def get_evaluation_config(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    return service.get_or_create_evaluation_config(db, domain_id)


@evaluation_config_router.put("/", response_model=models.DomainEvaluationConfigResponse)
def update_evaluation_config(
    db: DbSession,
    domain_id: UUID,
    update: models.DomainEvaluationConfigUpdate,
    _role: DomainRole = Depends(RequireDomainAdmin),
):
    return service.update_evaluation_config(db, domain_id, update)


@query_evaluation_router.get("/{query_log_id}/evaluation", response_model=models.EvaluationDetailResponse)
def get_query_evaluation(db: DbSession, query_log_id: UUID, current_user: CurrentUser):
    evaluation = service.get_evaluation(db, current_user, query_log_id)
    if evaluation is None:
        # The judge task hasn't created its row yet (dispatched, not
        # necessarily started) -- spec 4.3's "may be null if evaluation
        # not yet complete", rendered here as an explicit PENDING status
        # rather than a 404, since the query itself is real.
        return models.EvaluationDetailResponse(
            query_log_id=query_log_id, status=EvaluationStatus.PENDING,
            faithfulness=None, relevance=None, completeness=None, citation_accuracy=None,
            rationale=None, flagged=False, judge_provider=None, judge_model_version=None,
            error_message=None, overridden_by=None, override_rationale=None, overridden_at=None,
            original_scores=None, human_verdict=None,
        )
    return evaluation


@moderation_queue_router.get("/", response_model=List[models.EvaluationDetailResponse])
def get_moderation_queue(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    return service.get_moderation_queue(db, domain_id)


@moderation_queue_router.post("/{query_log_id}/override", response_model=models.EvaluationDetailResponse)
def override_evaluation(
    db: DbSession,
    domain_id: UUID,
    query_log_id: UUID,
    override: models.EvaluationOverrideRequest,
    current_user: CurrentUser,
    _role: DomainRole = Depends(RequireDomainAdmin),
):
    return service.override_evaluation(db, domain_id, query_log_id, current_user, override)


@moderation_queue_router.post("/{query_log_id}/verdict", response_model=models.EvaluationDetailResponse)
def set_evaluation_verdict(
    db: DbSession,
    domain_id: UUID,
    query_log_id: UUID,
    verdict: models.EvaluationVerdictRequest,
    current_user: CurrentUser,
    _role: DomainRole = Depends(RequireDomainAdmin),
):
    return service.set_evaluation_verdict(db, domain_id, query_log_id, current_user, verdict)


@quality_dashboard_router.get("/", response_model=models.QualityDashboardResponse)
def get_quality_dashboard(
    db: DbSession,
    domain_id: UUID,
    _role: DomainRole = Depends(RequireDomainAdmin),
    window_days: int = Query(default=30, ge=1, le=365),
    trend_points: int = Query(default=6, ge=1, le=24),
):
    return service.get_quality_dashboard(db, domain_id, window_days, trend_points)


@quality_dashboard_router.get("/export")
def export_quality_dashboard(
    db: DbSession,
    domain_id: UUID,
    _role: DomainRole = Depends(RequireDomainAdmin),
    window_days: int = Query(default=30, ge=1, le=365),
    trend_points: int = Query(default=6, ge=1, le=24),
):
    csv_body = service.export_quality_dashboard_csv(db, domain_id, window_days, trend_points)
    return Response(content=csv_body, media_type="text/csv")


@golden_qa_router.post("/", response_model=models.GoldenQAItemResponse, status_code=status.HTTP_201_CREATED)
def create_golden_qa_item(
    db: DbSession,
    domain_id: UUID,
    item: models.GoldenQAItemCreate,
    current_user: CurrentUser,
    _role: DomainRole = Depends(RequireDomainAdmin),
):
    return service.create_golden_qa_item(db, domain_id, current_user, item)


@golden_qa_router.get("/", response_model=List[models.GoldenQAItemResponse])
def list_golden_qa_items(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    return service.list_golden_qa_items(db, domain_id)


@golden_qa_router.get("/{item_id}", response_model=models.GoldenQAItemResponse)
def get_golden_qa_item(db: DbSession, domain_id: UUID, item_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    return service.get_golden_qa_item(db, domain_id, item_id)


@golden_qa_router.put("/{item_id}", response_model=models.GoldenQAItemResponse)
def update_golden_qa_item(
    db: DbSession,
    domain_id: UUID,
    item_id: UUID,
    update: models.GoldenQAItemCreate,
    _role: DomainRole = Depends(RequireDomainAdmin),
):
    return service.update_golden_qa_item(db, domain_id, item_id, update)


@golden_qa_router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_golden_qa_item(db: DbSession, domain_id: UUID, item_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    service.delete_golden_qa_item(db, domain_id, item_id)


@golden_qa_router.post("/run-regression", status_code=status.HTTP_202_ACCEPTED)
def trigger_golden_regression(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    # Enqueued, not run inline -- a real retrieval+generation+judge call
    # per golden item can take real wall-clock time.
    service.trigger_golden_regression(db, domain_id)
    return {"status": "enqueued"}
