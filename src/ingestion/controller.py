from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, UploadFile, File, status
from src.database.core import DbSession
from src.auth.service import CurrentUser
from src.entities.enums import DomainRole
from src.authz.dependencies import RequireDomainReader, RequireDomainContributor
from . import models
from . import service

router = APIRouter(
    prefix="/domains/{domain_id}/documents",
    tags=["Ingestion"]
)


@router.post("/", response_model=models.DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    db: DbSession,
    domain_id: UUID,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    _role: DomainRole = Depends(RequireDomainContributor),
):
    raw_bytes = await file.read()
    return service.create_document(
        db, domain_id, current_user.get_uuid(), file.filename, file.content_type, raw_bytes
    )


@router.get("/", response_model=List[models.DocumentResponse])
def list_documents(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainReader)):
    return service.list_documents(db, domain_id)


@router.get("/{document_id}", response_model=models.DocumentResponse)
def get_document(
    db: DbSession, domain_id: UUID, document_id: UUID, _role: DomainRole = Depends(RequireDomainReader)
):
    return service.get_document_or_raise(db, domain_id, document_id)
