"""Importing this package registers every mapped entity on `Base.metadata`
in one shot. Required wherever a process touches the DB without having
loaded all entity modules individually first -- the FastAPI app "gets
this for free" because its routers transitively import every entity, but
the Celery worker/beat processes only import what their tasks need
directly (e.g. `Document`), so without this, cross-entity foreign keys
(e.g. Document.domain_id -> domains.id) fail to resolve with
`NoReferencedTableError` the first time a worker process touches the DB.
See `tasks/celery_app.py`, which imports this package for exactly that
reason.
"""
from .user import User
from .domain import Domain
from .user_domain_role import UserDomainRole
from .document import Document
from .chunk import Chunk
from .domain_ingestion_config import DomainIngestionConfig
from .ontology_schema import OntologySchema
from .graph_node import GraphNode
from .graph_edge import GraphEdge
from .chunk_graph_node_link import ChunkGraphNodeLink
from .chunk_graph_edge_link import ChunkGraphEdgeLink
from .domain_retrieval_config import DomainRetrievalConfig
from .session_policy import SessionPolicy

__all__ = [
    "User", "Domain", "UserDomainRole", "Document", "Chunk", "DomainIngestionConfig", "OntologySchema",
    "GraphNode", "GraphEdge", "ChunkGraphNodeLink", "ChunkGraphEdgeLink", "DomainRetrievalConfig",
    "SessionPolicy",
]
