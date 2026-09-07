from uuid import UUID
from fastapi import Query
from src.database.core import DbSession
from src.auth.service import CurrentUser
from src.entities.user import User
from src.entities.enums import DomainRole, DOMAIN_ROLE_RANK
from src.exceptions import InsufficientPermissionsError
from . import service


def require_domain_role(minimum_role: DomainRole):
    """Dependency factory: binds `domain_id` from the route path and verifies,
    with a fresh DB read on every call, that the caller holds at least
    `minimum_role` in that domain. Never trusts anything from the JWT/client
    beyond the caller's identity.
    """

    def dependency(domain_id: UUID, current_user: CurrentUser, db: DbSession) -> DomainRole:
        role = service.get_effective_role(db, current_user.get_uuid(), domain_id)
        if role is None or DOMAIN_ROLE_RANK[role] < DOMAIN_ROLE_RANK[minimum_role]:
            raise InsufficientPermissionsError(domain_ids=[domain_id], required_role=minimum_role)
        return role

    return dependency


RequireDomainReader = require_domain_role(DomainRole.READER)
RequireDomainContributor = require_domain_role(DomainRole.CONTRIBUTOR)
RequireDomainAdmin = require_domain_role(DomainRole.ADMIN)


def require_platform_admin(current_user: CurrentUser, db: DbSession) -> User:
    user = db.query(User).filter(User.id == current_user.get_uuid()).first()
    if user is None or not user.is_platform_admin:
        raise InsufficientPermissionsError()
    return user


def require_domain_admin_or_platform_admin(domain_id: UUID, current_user: CurrentUser, db: DbSession) -> None:
    """For actions (like archiving a domain) allowed to either that domain's
    admin or a platform admin.
    """
    user = db.query(User).filter(User.id == current_user.get_uuid()).first()
    if user is not None and user.is_platform_admin:
        return
    role = service.get_effective_role(db, current_user.get_uuid(), domain_id)
    if role != DomainRole.ADMIN:
        raise InsufficientPermissionsError(domain_ids=[domain_id], required_role=DomainRole.ADMIN)


def require_all_domain_roles(minimum_role: DomainRole = DomainRole.READER):
    """For cross-domain query endpoints: verifies the caller holds at least
    `minimum_role` in every domain of `domain_ids` (repeated `domain_id` query
    params), e.g. `?domain_id=<uuid>&domain_id=<uuid>`.
    """

    def dependency(
        current_user: CurrentUser,
        db: DbSession,
        domain_ids: list[UUID] = Query(alias="domain_id"),
    ) -> list[UUID]:
        service.check_cross_domain_access(db, current_user.get_uuid(), domain_ids, minimum_role)
        return domain_ids

    return dependency
