"""Contract for future vector/graph retrieval modules (no retrieval code exists
yet in this repo). Any module that queries a vector store or graph DB for RAG
answers MUST call `build_retrieval_filter` before querying, and MUST stamp
every returned chunk/node with `attach_domain_provenance`. This is what
satisfies spec 1.3's "retrieval enforcement": results filtered server-side by
domain permissions, with domain provenance on every retrieved item.
"""
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID
from sqlalchemy.orm import Session
from src.entities.domain import Domain
from src.entities.enums import DomainRole
from src.auth.models import TokenData
from src.exceptions import InsufficientPermissionsError
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
    """Re-derives the permitted subset of `requested_domain_ids` server-side.
    Never trust `requested_domain_ids` as already-authorized just because the
    client sent it — every ID here is re-checked against user_domain_roles.
    Raises InsufficientPermissionsError if none of the requested domains are
    permitted.
    """
    user_id = current_user.get_uuid()
    permitted = [
        domain_id
        for domain_id in requested_domain_ids
        if service.has_minimum_role(db, user_id, domain_id, minimum_role)
    ]
    if not permitted:
        raise InsufficientPermissionsError(domain_ids=list(requested_domain_ids), required_role=minimum_role)
    return RetrievalFilter(user_id=user_id, permitted_domain_ids=permitted)


def attach_domain_provenance(domain_id: UUID, db: Session) -> DomainProvenance:
    """Every retrieved chunk/graph node must be stamped with this before
    leaving the retrieval layer, so the citation/LLM layer can prove which
    domain it came from.
    """
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    domain_name = domain.name if domain else str(domain_id)
    return DomainProvenance(domain_id=domain_id, domain_name=domain_name)
