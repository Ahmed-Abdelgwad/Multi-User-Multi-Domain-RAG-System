from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, UploadFile, File, status
from src.database.core import DbSession
from src.auth.service import CurrentUser
from src.entities.enums import DomainRole
from src.authz.dependencies import RequireDomainAdmin
from . import models
from . import service

# Admin-only end to end, per the plan ("ontology/ module: CRUD + YAML
# import, versioning, admin-only") -- unlike ingestion-config, even
# reading the schema is restricted here, since it directly shapes what
# phase 7's extraction is allowed to write to the graph.
router = APIRouter(
    prefix="/domains/{domain_id}/ontology",
    tags=["Ontology"],
)


@router.get("/", response_model=models.OntologySchemaResponse)
def get_active_schema(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    return service.get_active_schema_or_raise(db, domain_id)


@router.get("/versions", response_model=List[models.OntologySchemaResponse])
def list_schema_versions(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    return service.list_schema_versions(db, domain_id)


@router.post("/", response_model=models.OntologySchemaResponse, status_code=status.HTTP_201_CREATED)
def create_schema_version(
    db: DbSession,
    domain_id: UUID,
    create: models.OntologySchemaCreate,
    current_user: CurrentUser,
    _role: DomainRole = Depends(RequireDomainAdmin),
):
    return service.create_schema_version(db, domain_id, create, current_user.get_uuid())


@router.post("/import", response_model=models.OntologySchemaResponse, status_code=status.HTTP_201_CREATED)
async def import_schema(
    db: DbSession,
    domain_id: UUID,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    _role: DomainRole = Depends(RequireDomainAdmin),
):
    raw_yaml = await file.read()
    return service.import_schema_from_yaml(db, domain_id, raw_yaml, current_user.get_uuid())
