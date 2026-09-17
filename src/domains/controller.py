from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
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
from src.users import models as user_models
from src.users import service as user_service
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


@router.delete("/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_domain(
    db: DbSession,
    domain_id: UUID,
    _admin: User = Depends(require_platform_admin),
):
    # Platform-admin only (not domain-admin) -- this is irreversible and
    # spans Postgres, MinIO, and Neo4j, unlike archiving.
    service.delete_domain(db, domain_id)


@router.delete("/", response_model=List[UUID])
def delete_all_archived_domains(
    db: DbSession,
    _admin: User = Depends(require_platform_admin),
):
    return service.delete_all_archived_domains(db)


@router.get("/{domain_id}/roles", response_model=List[models.UserDomainRoleResponse])
def list_domain_roles(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainAdmin)):
    return service.list_domain_roles(db, domain_id)


@router.get("/{domain_id}/roles/lookup", response_model=List[user_models.UserResponse])
def lookup_users_to_invite(
    db: DbSession,
    domain_id: UUID,
    email: str = Query(min_length=2),
    _=Depends(require_domain_admin_or_platform_admin),
):
    # Scoped to "admin of this specific domain" rather than a global
    # /users/search -- narrows the "who can enumerate the user directory"
    # surface to the same trust boundary already used for archive_domain.
    return user_service.search_users_by_email(db, email)


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
