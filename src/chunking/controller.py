from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends
from src.database.core import DbSession
from src.auth.service import CurrentUser
from src.entities.enums import DomainRole
from src.authz.dependencies import RequireDomainReader, RequireDomainAdmin
from . import models
from . import service

ingestion_config_router = APIRouter(
    prefix="/domains/{domain_id}/ingestion-config",
    tags=["Ingestion Config"],
)


@ingestion_config_router.get("/", response_model=models.DomainIngestionConfigResponse)
def get_ingestion_config(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    return service.get_or_create_ingestion_config(db, domain_id)


@ingestion_config_router.put("/", response_model=models.DomainIngestionConfigResponse)
def update_ingestion_config(
    db: DbSession,
    domain_id: UUID,
    update: models.DomainIngestionConfigUpdate,
    current_user: CurrentUser,
    _role: DomainRole = Depends(RequireDomainAdmin),
):
    return service.update_ingestion_config(db, domain_id, update, current_user.get_uuid())


chunks_router = APIRouter(
    prefix="/domains/{domain_id}/documents/{document_id}/chunks",
    tags=["Ingestion"],
)


@chunks_router.get("/", response_model=List[models.ChunkResponse])
def list_chunks(
    db: DbSession, domain_id: UUID, document_id: UUID, _role: DomainRole = Depends(RequireDomainReader)
):
    return service.list_chunks(db, domain_id, document_id)
