"""Any module that queries a vector store or graph DB for RAG answers MUST
call `build_retrieval_filter` before querying, and MUST stamp every returned
chunk/node with `attach_domain_provenance`. This is what satisfies spec 1.3's
"retrieval enforcement": results filtered server-side by domain permissions,
with domain provenance on every retrieved item.
"""
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID
from sqlalchemy.orm import Session
from src.entities.domain import Domain
from src.entities.enums import DomainRole
from src.auth.models import TokenData
from src.domains.service import raise_if_archived
from . import service


@dataclass(frozen=True)
class DomainProvenance:
    domain_id: UUID
    domain_name: str


@dataclass(frozen=True)
class RetrievalFilter:
    user_id: UUID
    permitted_domain_ids: list[UUID]


def build_retrieval_filter(
    db: Session,
    current_user: TokenData,
    requested_domain_ids: Sequence[UUID],
    minimum_role: DomainRole = DomainRole.READER,
) -> RetrievalFilter:
    """Spec 1.3: "Cross-domain queries permitted only when the requesting
    user holds valid permissions in all target domains" -- all-or-nothing,
    not a best-effort search over whichever subset the user happens to be
    permitted in. Never trust `requested_domain_ids` as already-authorized
    just because the client sent it -- every ID here is re-checked against
    user_domain_roles (via service.check_cross_domain_access). Permission
    is checked *before* the archived check, so a caller with no access to
    a domain gets the same 403 whether it's archived, active, or doesn't
    exist at all -- archived status is only revealed once the caller is
    already confirmed to hold a role there (a query is new use of a
    domain, same as a write, so an archived one is rejected outright).
    Raises InsufficientPermissionsError naming every domain the user lacks
    `minimum_role` in, or DomainArchivedError naming the first archived
    domain found.
    """
    user_id = current_user.get_uuid()
    service.check_cross_domain_access(db, user_id, requested_domain_ids, minimum_role)
    for domain_id in requested_domain_ids:
        raise_if_archived(db, domain_id)
    return RetrievalFilter(user_id=user_id, permitted_domain_ids=list(requested_domain_ids))


def attach_domain_provenance(domain_id: UUID, db: Session) -> DomainProvenance:
    """Every retrieved chunk/graph node must be stamped with this before
    leaving the retrieval layer, so the citation/LLM layer can prove which
    domain it came from.
    """
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    domain_name = domain.name if domain else str(domain_id)
    return DomainProvenance(domain_id=domain_id, domain_name=domain_name)
