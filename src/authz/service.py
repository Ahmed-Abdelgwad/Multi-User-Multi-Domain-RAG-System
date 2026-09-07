from typing import Sequence
from uuid import UUID
from sqlalchemy.orm import Session
from src.entities.user_domain_role import UserDomainRole
from src.entities.enums import DomainRole, DOMAIN_ROLE_RANK
from src.exceptions import InsufficientPermissionsError


def get_effective_role(db: Session, user_id: UUID, domain_id: UUID) -> DomainRole | None:
    row = (
        db.query(UserDomainRole)
        .filter(UserDomainRole.user_id == user_id, UserDomainRole.domain_id == domain_id)
        .first()
    )
    return row.role if row else None


def has_minimum_role(db: Session, user_id: UUID, domain_id: UUID, minimum_role: DomainRole) -> bool:
    role = get_effective_role(db, user_id, domain_id)
    if role is None:
        return False
    return DOMAIN_ROLE_RANK[role] >= DOMAIN_ROLE_RANK[minimum_role]


def get_domains_missing_role(
    db: Session, user_id: UUID, domain_ids: Sequence[UUID], minimum_role: DomainRole
) -> list[UUID]:
    return [
        domain_id
        for domain_id in domain_ids
        if not has_minimum_role(db, user_id, domain_id, minimum_role)
    ]


def check_cross_domain_access(
    db: Session, user_id: UUID, domain_ids: Sequence[UUID], minimum_role: DomainRole = DomainRole.READER
) -> None:
    """Raises InsufficientPermissionsError if the user lacks minimum_role in ANY of domain_ids."""
    missing = get_domains_missing_role(db, user_id, domain_ids, minimum_role)
    if missing:
        raise InsufficientPermissionsError(domain_ids=missing, required_role=minimum_role)


def list_user_domain_roles(db: Session, user_id: UUID) -> list[UserDomainRole]:
    return db.query(UserDomainRole).filter(UserDomainRole.user_id == user_id).all()
