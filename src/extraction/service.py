import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from src.entities.chunk import Chunk
from src.entities.document import Document
from src.entities.graph_node import GraphNode
from src.entities.graph_edge import GraphEdge
from src.entities.chunk_graph_node_link import ChunkGraphNodeLink
from src.entities.chunk_graph_edge_link import ChunkGraphEdgeLink
from src.entities.ontology_schema import OntologySchema
from src.exceptions import OntologySchemaNotFoundError
from src.ontology.service import get_active_schema_or_raise

# A node's description is grown from a snippet of the chunk it was
# mentioned in, not the whole chunk -- keeps `graph_nodes.description`
# from growing unboundedly across many mentions.
DESCRIPTION_SNIPPET_CHARS = 280


def _normalize(name: str) -> str:
    return name.strip().lower()


def _get_or_touch_node(
    db: Session, domain_id: UUID, type_: str, name: str, ontology_version: int, extractor_version: str
) -> GraphNode:
    name = name.strip()
    name_key = _normalize(name)
    node = (
        db.query(GraphNode)
        .filter(GraphNode.domain_id == domain_id, GraphNode.type == type_, GraphNode.name_key == name_key)
        .first()
    )
    if node:
        node.ontology_version = ontology_version
        node.extractor_model_version = extractor_version
        node.updated_at = datetime.now(timezone.utc)
        return node

    node = GraphNode(
        id=uuid4(), domain_id=domain_id, type=type_, name=name, name_key=name_key,
        ontology_version=ontology_version, extractor_model_version=extractor_version,
    )
    db.add(node)
    db.flush()
    return node


def _append_description(node: GraphNode, occurrence_text: str) -> None:
    snippet = occurrence_text.strip()[:DESCRIPTION_SNIPPET_CHARS]
    if not snippet or (node.description and snippet in node.description):
        return
    node.description = f"{node.description}\n{snippet}" if node.description else snippet


def _link_node_to_chunk(db: Session, chunk_id: UUID, node_id: UUID) -> None:
    exists = (
        db.query(ChunkGraphNodeLink)
        .filter(ChunkGraphNodeLink.chunk_id == chunk_id, ChunkGraphNodeLink.graph_node_id == node_id)
        .first()
    )
    if not exists:
        db.add(ChunkGraphNodeLink(id=uuid4(), chunk_id=chunk_id, graph_node_id=node_id))
        # Flushed immediately (session's autoflush is off, see
        # database/core.py) so a second mention of the *same* entity
        # later in this same chunk sees this pending insert on its own
        # exists-check instead of racing it -- found live against a real
        # CV, where a skill/tool name is often mentioned more than once
        # within one chunk, which raised a UniqueViolation on
        # `uq_chunk_graph_node_links_pair` before this fix.
        db.flush()


def _get_or_touch_edge(
    db: Session, domain_id: UUID, source_node_id: UUID, target_node_id: UUID,
    predicate: str, ontology_version: int, extractor_version: str,
) -> GraphEdge:
    edge = (
        db.query(GraphEdge)
        .filter(
            GraphEdge.domain_id == domain_id,
            GraphEdge.source_node_id == source_node_id,
            GraphEdge.target_node_id == target_node_id,
            GraphEdge.predicate == predicate,
        )
        .first()
    )
    if edge:
        edge.ontology_version = ontology_version
        edge.extractor_model_version = extractor_version
        edge.updated_at = datetime.now(timezone.utc)
        return edge

    edge = GraphEdge(
        id=uuid4(), domain_id=domain_id, source_node_id=source_node_id, target_node_id=target_node_id,
        predicate=predicate, ontology_version=ontology_version, extractor_model_version=extractor_version,
    )
    db.add(edge)
    db.flush()
    return edge


def _link_edge_to_chunk_and_recompute_mentions(db: Session, chunk_id: UUID, edge: GraphEdge) -> None:
    exists = (
        db.query(ChunkGraphEdgeLink)
        .filter(ChunkGraphEdgeLink.chunk_id == chunk_id, ChunkGraphEdgeLink.graph_edge_id == edge.id)
        .first()
    )
    if not exists:
        db.add(ChunkGraphEdgeLink(id=uuid4(), chunk_id=chunk_id, graph_edge_id=edge.id))
        db.flush()

    edge.mention_count = (
        db.query(ChunkGraphEdgeLink).filter(ChunkGraphEdgeLink.graph_edge_id == edge.id).count()
    )


def process_extract_entities_for_chunk(
    db: Session, chunk: Chunk, schema: OntologySchema, extractor_version: str
) -> None:
    """Extracts entities/relations from one chunk's content and upserts
    them into the domain's knowledge graph. Entities are upserted (and
    linked to this chunk) regardless of whether they participate in any
    relation -- an entity mentioned with no captured relationship is still
    a real node. Triples are only turned into edges when both endpoints
    were themselves extracted from this same chunk (JointIE's own output
    guarantees this).
    """
    from . import extractor

    output = extractor.extract(chunk.content, schema.node_types, schema.relation_types)

    nodes_by_key: dict[tuple[str, str], GraphNode] = {}
    for entity in output.entities:
        node = _get_or_touch_node(
            db, chunk.domain_id, entity.type, entity.name, schema.version, extractor_version
        )
        _append_description(node, chunk.content)
        _link_node_to_chunk(db, chunk.id, node.id)
        nodes_by_key[(entity.type, _normalize(entity.name))] = node

    for triple in output.triples:
        source = nodes_by_key.get((triple.subject.type, _normalize(triple.subject.name)))
        target = nodes_by_key.get((triple.object.type, _normalize(triple.object.name)))
        if not source or not target:
            continue
        edge = _get_or_touch_edge(
            db, chunk.domain_id, source.id, target.id, triple.predicate, schema.version, extractor_version
        )
        _link_edge_to_chunk_and_recompute_mentions(db, chunk.id, edge)


def process_extract_entities_for_document(db: Session, document_id: UUID) -> None:
    """Runs inside the Celery worker (phase 7, spec 2.5), fired by the
    periodic `batch_extract_entities_task` (tasks/pipeline.py) -- not
    chained directly off `chunk_and_embed_task`, per the plan's canonical
    2.5 text ("runs as a background batch job post-ingest ... graph lags
    behind vector index by one job cycle, acceptable for MVP").

    Processes every active chunk of this document that hasn't been
    extracted yet (`entities_extracted_at IS NULL`). Skips gracefully
    (not a failure) if the domain has no active ontology yet -- extraction
    simply hasn't been configured for that domain, same as a domain never
    touching ingestion never getting a `DomainIngestionConfig` row.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        logging.error(f"process_extract_entities_for_document: document {document_id} not found")
        return

    try:
        schema = get_active_schema_or_raise(db, document.domain_id)
    except OntologySchemaNotFoundError:
        logging.info(
            f"Document {document_id}: no active ontology for domain {document.domain_id}, skipping extraction"
        )
        return

    chunks = (
        db.query(Chunk)
        .filter(
            Chunk.document_id == document_id,
            Chunk.is_active.is_(True),
            Chunk.entities_extracted_at.is_(None),
        )
        .all()
    )
    if not chunks:
        return

    from . import extractor
    extractor_version = extractor.extractor_model_version()

    # Committed per chunk, not once for the whole document: each chunk
    # runs the (expensive) model independently, so one chunk's failure
    # must not discard every other chunk's already-successful work in
    # the same pass -- found live on a real 25-chunk document, where a
    # single UniqueViolation on one chunk rolled back all 25 chunks'
    # extractions under the previous single-transaction version. A
    # failed chunk simply keeps `entities_extracted_at = NULL`, so the
    # next batch tick retries just that one.
    processed = 0
    for chunk in chunks:
        try:
            process_extract_entities_for_chunk(db, chunk, schema, extractor_version)
            chunk.entities_extracted_at = datetime.now(timezone.utc)
            db.commit()
            processed += 1
        except Exception as e:
            logging.error(f"Document {document_id} chunk {chunk.id} entity extraction failed: {e}")
            db.rollback()

    logging.info(f"Document {document_id}: extracted entities/relations for {processed}/{len(chunks)} chunk(s)")


# --- read-only graph queries (thin inspection endpoints, RBAC-filtered
# like every other domain-scoped resource) ---

def list_graph_nodes(db: Session, domain_id: UUID) -> list[GraphNode]:
    return db.query(GraphNode).filter(GraphNode.domain_id == domain_id).order_by(GraphNode.name).all()


def list_graph_edges(db: Session, domain_id: UUID) -> list[GraphEdge]:
    return db.query(GraphEdge).filter(GraphEdge.domain_id == domain_id).all()


def list_chunk_ids_for_node(db: Session, domain_id: UUID, node_id: UUID) -> list[UUID]:
    return [
        row[0] for row in
        db.query(ChunkGraphNodeLink.chunk_id)
        .join(GraphNode, GraphNode.id == ChunkGraphNodeLink.graph_node_id)
        .filter(GraphNode.domain_id == domain_id, ChunkGraphNodeLink.graph_node_id == node_id)
        .all()
    ]


def list_chunk_ids_for_edge(db: Session, domain_id: UUID, edge_id: UUID) -> list[UUID]:
    return [
        row[0] for row in
        db.query(ChunkGraphEdgeLink.chunk_id)
        .join(GraphEdge, GraphEdge.id == ChunkGraphEdgeLink.graph_edge_id)
        .filter(GraphEdge.domain_id == domain_id, ChunkGraphEdgeLink.graph_edge_id == edge_id)
        .all()
    ]


def list_nodes_for_chunk(db: Session, domain_id: UUID, chunk_id: UUID) -> list[GraphNode]:
    return (
        db.query(GraphNode)
        .join(ChunkGraphNodeLink, ChunkGraphNodeLink.graph_node_id == GraphNode.id)
        .filter(GraphNode.domain_id == domain_id, ChunkGraphNodeLink.chunk_id == chunk_id)
        .all()
    )


def list_edges_for_chunk(db: Session, domain_id: UUID, chunk_id: UUID) -> list[GraphEdge]:
    return (
        db.query(GraphEdge)
        .join(ChunkGraphEdgeLink, ChunkGraphEdgeLink.graph_edge_id == GraphEdge.id)
        .filter(GraphEdge.domain_id == domain_id, ChunkGraphEdgeLink.chunk_id == chunk_id)
        .all()
    )
