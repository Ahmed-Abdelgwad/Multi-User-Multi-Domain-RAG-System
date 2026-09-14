from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends
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
        )
    return evaluation


@moderation_queue_router.get("/", response_model=List[models.EvaluationDetailResponse])
def get_moderation_queue(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    return service.get_moderation_queue(db, domain_id)
