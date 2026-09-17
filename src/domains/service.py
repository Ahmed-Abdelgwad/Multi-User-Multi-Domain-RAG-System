from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from . import models
from src.entities.domain import Domain
from src.entities.user import User
from src.entities.user_domain_role import UserDomainRole
from src.entities.document import Document
from src.entities.chunk import Chunk
from src.entities.graph_node import GraphNode
from src.entities.graph_edge import GraphEdge
from src.entities.chunk_graph_node_link import ChunkGraphNodeLink
from src.entities.chunk_graph_edge_link import ChunkGraphEdgeLink
from src.entities.domain_ingestion_config import DomainIngestionConfig
from src.entities.domain_retrieval_config import DomainRetrievalConfig
from src.entities.domain_evaluation_config import DomainEvaluationConfig
from src.entities.golden_qa_item import GoldenQAItem
from src.entities.ontology_schema import OntologySchema
from src.entities.query_log import QueryLog
from src.entities.evaluation_result import EvaluationResult
from src.entities.enums import DomainRole
from src.exceptions import DomainNotFoundError, DomainArchivedError, DomainNotArchivedError, DuplicateDomainNameError
from src.storage.core import delete_object
from src.extraction.graph_store import delete_domain_graph
import logging


def get_domain_or_raise(db: Session, domain_id: UUID) -> Domain:
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise DomainNotFoundError(domain_id)
    return domain


def raise_if_archived(db: Session, domain_id: UUID) -> None:
    """Spec 1.3: an archived domain is frozen for new activity -- called
    from every write path (uploads, config/schema changes) and from the
    retrieval path (authz/retrieval.py), not just role assignment. Reads
    (domain detail, existing chunks/graph data, config GETs) are left
    alone -- archiving stops new use, it doesn't hide history.
    """
    if get_domain_or_raise(db, domain_id).is_archived:
        raise DomainArchivedError(domain_id)


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


def delete_domain(db: Session, domain_id: UUID) -> None:
    """Hard delete -- irreversible, only allowed once a domain is already
    archived (the safety rail: archive is the "stop using this" step,
    delete is the "actually get rid of it" step, and requiring the first
    before the second makes an accidental hard delete much harder).

    Postgres has no FK cascades configured for domain-scoped tables (see
    the migrations), so every table is cleared explicitly here, in
    dependency order, plus the two external stores (MinIO, Neo4j) that
    Postgres doesn't know about at all.
    """
    domain = get_domain_or_raise(db, domain_id)
    if not domain.is_archived:
        raise DomainNotArchivedError(domain_id)

    documents = db.query(Document).filter(Document.domain_id == domain_id).all()
    for document in documents:
        try:
            delete_object(document.storage_key)
        except Exception as e:
            logging.warning(f"Failed to delete storage object for document {document.id}: {e}")

    try:
        delete_domain_graph(domain_id)
    except Exception as e:
        logging.warning(f"Failed to delete graph data for domain {domain_id}: {e}")

    chunk_ids = [row.id for row in db.query(Chunk.id).filter(Chunk.domain_id == domain_id).all()]
    graph_node_ids = [row.id for row in db.query(GraphNode.id).filter(GraphNode.domain_id == domain_id).all()]
    graph_edge_ids = [row.id for row in db.query(GraphEdge.id).filter(GraphEdge.domain_id == domain_id).all()]

    if chunk_ids:
        db.query(ChunkGraphNodeLink).filter(ChunkGraphNodeLink.chunk_id.in_(chunk_ids)).delete(synchronize_session=False)
        db.query(ChunkGraphEdgeLink).filter(ChunkGraphEdgeLink.chunk_id.in_(chunk_ids)).delete(synchronize_session=False)
    if graph_node_ids:
        db.query(ChunkGraphNodeLink).filter(ChunkGraphNodeLink.graph_node_id.in_(graph_node_ids)).delete(synchronize_session=False)
    if graph_edge_ids:
        db.query(ChunkGraphEdgeLink).filter(ChunkGraphEdgeLink.graph_edge_id.in_(graph_edge_ids)).delete(synchronize_session=False)

    db.query(GraphEdge).filter(GraphEdge.domain_id == domain_id).delete(synchronize_session=False)
    db.query(GraphNode).filter(GraphNode.domain_id == domain_id).delete(synchronize_session=False)
    db.query(Chunk).filter(Chunk.domain_id == domain_id).delete(synchronize_session=False)

    # domain_ids is a JSON array (a query can span multiple domains), not
    # a plain FK column, so it can't be filtered in SQL -- matching the
    # existing convention elsewhere in this codebase (evaluation/service.py)
    # of filtering it in Python. A query log that touched this domain is
    # deleted outright rather than having the id stripped from its list:
    # once the domain's chunks are gone the log's sources are already
    # unrecoverable, so keeping a partial record isn't meaningfully safer.
    domain_id_str = str(domain_id)
    affected_query_logs = [ql for ql in db.query(QueryLog).all() if domain_id_str in ql.domain_ids]
    for query_log in affected_query_logs:
        db.query(EvaluationResult).filter(EvaluationResult.query_log_id == query_log.id).delete(synchronize_session=False)
        db.delete(query_log)

    db.query(GoldenQAItem).filter(GoldenQAItem.domain_id == domain_id).delete(synchronize_session=False)
    db.query(OntologySchema).filter(OntologySchema.domain_id == domain_id).delete(synchronize_session=False)
    db.query(DomainIngestionConfig).filter(DomainIngestionConfig.domain_id == domain_id).delete(synchronize_session=False)
    db.query(DomainRetrievalConfig).filter(DomainRetrievalConfig.domain_id == domain_id).delete(synchronize_session=False)
    db.query(DomainEvaluationConfig).filter(DomainEvaluationConfig.domain_id == domain_id).delete(synchronize_session=False)
    db.query(Document).filter(Document.domain_id == domain_id).delete(synchronize_session=False)
    db.query(UserDomainRole).filter(UserDomainRole.domain_id == domain_id).delete(synchronize_session=False)

    db.delete(domain)
    db.commit()
    logging.info(
        f"Domain {domain_id} hard-deleted ({len(documents)} documents, "
        f"{len(chunk_ids)} chunks, {len(affected_query_logs)} query logs)"
    )
    # AUDIT HOOK: record domain hard delete


def delete_all_archived_domains(db: Session) -> list[UUID]:
    domain_ids = [row.id for row in db.query(Domain.id).filter(Domain.is_archived.is_(True)).all()]
    for domain_id in domain_ids:
        delete_domain(db, domain_id)
    return domain_ids


def list_domains_for_user(db: Session, user_id: UUID, is_platform_admin: bool = False) -> list[Domain]:
    if is_platform_admin:
        return db.query(Domain).all()
    return (
        db.query(Domain)
        .join(UserDomainRole, UserDomainRole.domain_id == Domain.id)
        .filter(UserDomainRole.user_id == user_id)
        .all()
    )


def list_domain_roles(db: Session, domain_id: UUID) -> list[models.UserDomainRoleResponse]:
    get_domain_or_raise(db, domain_id)
    rows = (
        db.query(UserDomainRole, User.email)
        .join(User, User.id == UserDomainRole.user_id)
        .filter(UserDomainRole.domain_id == domain_id)
        .all()
    )
    return [
        models.UserDomainRoleResponse(
            user_id=role.user_id, domain_id=role.domain_id, role=role.role,
            granted_at=role.granted_at, user_email=email,
        )
        for role, email in rows
    ]


def assign_role(db: Session, domain_id: UUID, request: models.AssignRoleRequest, granted_by: UUID) -> UserDomainRole:
    raise_if_archived(db, domain_id)

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
