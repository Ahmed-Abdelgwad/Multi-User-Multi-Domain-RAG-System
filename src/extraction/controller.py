from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends
from src.database.core import DbSession
from src.entities.enums import DomainRole
from src.authz.dependencies import RequireDomainReader
from . import models, service

# Read-only inspection of the domain's knowledge graph (spec 2.5). Writing
# happens only from the extraction pipeline itself (tasks/pipeline.py),
# never through this API.
router = APIRouter(
    prefix="/domains/{domain_id}/graph",
    tags=["Knowledge Graph"],
)


@router.get("/nodes", response_model=List[models.GraphNodeResponse])
def list_graph_nodes(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainReader)):
    return service.list_graph_nodes(db, domain_id)


@router.get("/edges", response_model=List[models.GraphEdgeResponse])
def list_graph_edges(db: DbSession, domain_id: UUID, _role: DomainRole = Depends(RequireDomainReader)):
    return service.list_graph_edges(db, domain_id)


@router.get("/nodes/{node_id}/chunks", response_model=List[UUID])
def list_chunks_for_node(
    db: DbSession, domain_id: UUID, node_id: UUID, _role: DomainRole = Depends(RequireDomainReader)
):
    return service.list_chunk_ids_for_node(db, domain_id, node_id)


@router.get("/edges/{edge_id}/chunks", response_model=List[UUID])
def list_chunks_for_edge(
    db: DbSession, domain_id: UUID, edge_id: UUID, _role: DomainRole = Depends(RequireDomainReader)
):
    return service.list_chunk_ids_for_edge(db, domain_id, edge_id)


@router.get("/chunks/{chunk_id}/nodes", response_model=List[models.GraphNodeResponse])
def list_nodes_for_chunk(
    db: DbSession, domain_id: UUID, chunk_id: UUID, _role: DomainRole = Depends(RequireDomainReader)
):
    return service.list_nodes_for_chunk(db, domain_id, chunk_id)


@router.get("/chunks/{chunk_id}/edges", response_model=List[models.GraphEdgeResponse])
def list_edges_for_chunk(
    db: DbSession, domain_id: UUID, chunk_id: UUID, _role: DomainRole = Depends(RequireDomainReader)
):
    return service.list_edges_for_chunk(db, domain_id, chunk_id)
