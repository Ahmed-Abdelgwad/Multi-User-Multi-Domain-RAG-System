from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, status
from src.database.core import DbSession
from src.auth.service import CurrentUser
from src.entities.user import User
from src.entities.enums import DomainRole
from src.authz.dependencies import (
    RequireDomainReader,
    RequireDomainAdmin,
    require_platform_admin,
    require_domain_admin_or_platform_admin,
)
from . import models
from . import service

router = APIRouter(
    prefix="/domains",
    tags=["Domains"]
)


@router.post("/", response_model=models.DomainResponse, status_code=status.HTTP_201_CREATED)
def create_domain(
    db: DbSession,
    domain_create: models.DomainCreate,
    admin: User = Depends(require_platform_admin),
):
    return service.create_domain(db, domain_create, admin.id)


@router.get("/", response_model=List[models.DomainResponse])
def list_domains(db: DbSession, current_user: CurrentUser):
    user = db.query(User).filter(User.id == current_user.get_uuid()).first()
    is_platform_admin = bool(user and user.is_platform_admin)
    return service.list_domains_for_user(db, current_user.get_uuid(), is_platform_admin)


@router.get("/{domain_id}", response_model=models.DomainResponse)
def get_domain(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainReader)):
    return service.get_domain_or_raise(db, domain_id)


@router.post("/{domain_id}/archive", response_model=models.DomainResponse)
def archive_domain(
    db: DbSession,
    domain_id: UUID,
    current_user: CurrentUser,
    _=Depends(require_domain_admin_or_platform_admin),
):
    return service.archive_domain(db, domain_id, current_user.get_uuid())


@router.get("/{domain_id}/roles", response_model=List[models.UserDomainRoleResponse])
def list_domain_roles(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    return service.list_domain_roles(db, domain_id)


@router.post("/{domain_id}/roles", response_model=models.UserDomainRoleResponse, status_code=status.HTTP_201_CREATED)
def assign_role(
    db: DbSession,
    domain_id: UUID,
    request: models.AssignRoleRequest,
    current_user: CurrentUser,
    _role: DomainRole = Depends(RequireDomainAdmin),
):
    return service.assign_role(db, domain_id, request, current_user.get_uuid())


@router.delete("/{domain_id}/roles/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_role(db: DbSession, domain_id: UUID, user_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    service.revoke_role(db, domain_id, user_id)
