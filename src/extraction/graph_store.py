from uuid import UUID
from src.entities.graph_node import GraphNode
from src.entities.graph_edge import GraphEdge
from src.graph.client import get_graph_client

# Spec 3.2's graph store, kept in sync with the Postgres graph_nodes/
# graph_edges tables by an inline dual-write (see extraction/service.py)
# rather than a separate sync job. MERGE keys mirror the Postgres unique
# constraints exactly: (domain_id, type, name_key) for nodes,
# (domain_id, source_node_id, target_node_id, predicate) for edges.
# `chunk_ids` is appended-if-absent via a pure-Cypher FOREACH/CASE idiom
# (no APOC) so a repeat mention of the same entity/relation in a
# different chunk grows the list instead of duplicating or overwriting.

_UPSERT_NODE = """
MERGE (e:Entity {domain_id: $domain_id, type: $type, name_key: $name_key})
ON CREATE SET e.id = $id, e.name = $name, e.description = $description, e.chunk_ids = [$chunk_id]
ON MATCH SET e.name = $name, e.description = $description
WITH e
FOREACH (_ IN CASE WHEN $chunk_id IN e.chunk_ids THEN [] ELSE [1] END |
    SET e.chunk_ids = e.chunk_ids + $chunk_id
)
"""

_UPSERT_EDGE = """
MATCH (source:Entity {id: $source_id})
MATCH (target:Entity {id: $target_id})
MERGE (source)-[r:RELATES {predicate: $predicate, domain_id: $domain_id}]->(target)
ON CREATE SET r.mention_count = $mention_count, r.chunk_ids = [$chunk_id]
ON MATCH SET r.mention_count = $mention_count
WITH r
FOREACH (_ IN CASE WHEN $chunk_id IN r.chunk_ids THEN [] ELSE [1] END |
    SET r.chunk_ids = r.chunk_ids + $chunk_id
)
"""


def upsert_node_to_graph(node: GraphNode, chunk_id: UUID) -> None:
    get_graph_client().query(_UPSERT_NODE, {
        "id": str(node.id),
        "domain_id": str(node.domain_id),
        "type": node.type,
        "name": node.name,
        "name_key": node.name_key,
        "description": node.description,
        "chunk_id": str(chunk_id),
    })


def upsert_edge_to_graph(edge: GraphEdge, chunk_id: UUID) -> None:
    get_graph_client().query(_UPSERT_EDGE, {
        "source_id": str(edge.source_node_id),
        "target_id": str(edge.target_node_id),
        "predicate": edge.predicate,
        "domain_id": str(edge.domain_id),
        "mention_count": edge.mention_count,
        "chunk_id": str(chunk_id),
    })
