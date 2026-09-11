from uuid import UUID
from fastapi import APIRouter, Depends
from src.database.core import DbSession
from src.entities.enums import DomainRole
from src.authz.dependencies import RequireDomainAdmin
from src.auth.service import CurrentUser
from . import models
from . import service

retrieval_config_router = APIRouter(
    prefix="/domains/{domain_id}/retrieval-config",
    tags=["Retrieval Config"],
)

query_router = APIRouter(prefix="/query", tags=["Query"])


@retrieval_config_router.get("/", response_model=models.DomainRetrievalConfigResponse)
def get_retrieval_config(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    return service.get_or_create_retrieval_config(db, domain_id)


@retrieval_config_router.put("/", response_model=models.DomainRetrievalConfigResponse)
def update_retrieval_config(
    db: DbSession,
    domain_id: UUID,
    update: models.DomainRetrievalConfigUpdate,
    _role: DomainRole = Depends(RequireDomainAdmin),
):
    return service.update_retrieval_config(db, domain_id, update)


@query_router.post("/", response_model=models.QueryResponse)
def query(db: DbSession, request: models.QueryRequest, current_user: CurrentUser):
    # No RequireDomain*: build_retrieval_filter (inside answer_query)
    # silently drops domains the user can't read and only 403s if none
    # of the requested domains are permitted at all.
    result = service.answer_query(db, current_user, request.query, request.domain_ids)
    sources = [
        models.QuerySource(
            chunk_id=doc.metadata["chunk_id"],
            domain_id=doc.metadata["domain_id"],
            domain_name=doc.metadata["domain_name"],
            content_type=doc.metadata["content_type"],
            score=doc.metadata.get("vector_score", doc.metadata.get("graph_score")),
        )
        for doc in result["documents"]
    ]
    return models.QueryResponse(
        answer=result["answer"],
        route=result["route"],
        confidence=result["confidence"],
        low_confidence=result["low_confidence"],
        entities=result["entities"],
        sources=sources,
    )
