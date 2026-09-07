from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from . import models
from src.entities.domain import Domain
from src.entities.user_domain_role import UserDomainRole
from src.entities.enums import DomainRole
from src.exceptions import DomainNotFoundError, DomainArchivedError, DuplicateDomainNameError
import logging


def get_domain_or_raise(db: Session, domain_id: UUID) -> Domain:
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise DomainNotFoundError(domain_id)
    return domain


def create_domain(db: Session, domain_create: models.DomainCreate, created_by: UUID) -> Domain:
    if db.query(Domain).filter(Domain.name == domain_create.name).first():
        raise DuplicateDomainNameError(domain_create.name)

    domain = Domain(
        id=uuid4(),
        name=domain_create.name,
        description=domain_create.description,
        created_by=created_by,
    )
    db.add(domain)
    db.flush()

    # Creator is auto-granted domain_admin so the domain isn't orphaned
    # (only a platform admin could create it, but per-domain admin from here on).
    db.add(UserDomainRole(id=uuid4(), user_id=created_by, domain_id=domain.id, role=DomainRole.ADMIN))
    db.commit()
    db.refresh(domain)
    logging.info(f"Domain '{domain.name}' created by {created_by}")
    # AUDIT HOOK: record domain creation
    return domain


def archive_domain(db: Session, domain_id: UUID, archived_by: UUID) -> Domain:
    domain = get_domain_or_raise(db, domain_id)
    domain.is_archived = True
    domain.archived_at = datetime.now(timezone.utc)
    domain.archived_by = archived_by
    db.commit()
    db.refresh(domain)
    logging.info(f"Domain {domain_id} archived by {archived_by}")
    # AUDIT HOOK: record domain archive
    return domain


def list_domains_for_user(db: Session, user_id: UUID, is_platform_admin: bool = False) -> list[Domain]:
    if is_platform_admin:
        return db.query(Domain).all()
    return (
        db.query(Domain)
        .join(UserDomainRole, UserDomainRole.domain_id == Domain.id)
        .filter(UserDomainRole.user_id == user_id)
        .all()
    )


def list_domain_roles(db: Session, domain_id: UUID) -> list[UserDomainRole]:
    get_domain_or_raise(db, domain_id)
    return db.query(UserDomainRole).filter(UserDomainRole.domain_id == domain_id).all()


def assign_role(db: Session, domain_id: UUID, request: models.AssignRoleRequest, granted_by: UUID) -> UserDomainRole:
    domain = get_domain_or_raise(db, domain_id)
    if domain.is_archived:
        raise DomainArchivedError(domain_id)

    existing = (
        db.query(UserDomainRole)
        .filter(UserDomainRole.user_id == request.user_id, UserDomainRole.domain_id == domain_id)
        .first()
    )
    if existing:
        existing.role = request.role
        existing.granted_by = granted_by
        existing.granted_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        logging.info(f"Role for user {request.user_id} on domain {domain_id} updated to {request.role} by {granted_by}")
        # AUDIT HOOK: record role update
        return existing

    role = UserDomainRole(
        id=uuid4(),
        user_id=request.user_id,
        domain_id=domain_id,
        role=request.role,
        granted_by=granted_by,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    logging.info(f"Role {request.role} granted to user {request.user_id} on domain {domain_id} by {granted_by}")
    # AUDIT HOOK: record role grant
    return role


def revoke_role(db: Session, domain_id: UUID, user_id: UUID) -> None:
    get_domain_or_raise(db, domain_id)
    existing = (
        db.query(UserDomainRole)
        .filter(UserDomainRole.user_id == user_id, UserDomainRole.domain_id == domain_id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        logging.info(f"Role for user {user_id} on domain {domain_id} revoked")
        # AUDIT HOOK: record role revoke
