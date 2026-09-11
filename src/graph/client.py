from functools import lru_cache
from ..config import get_settings

# Spec 3.2: one generic node label/relationship type, ontology `type`/
# `predicate` values live as properties (Cypher can't parameterize
# labels/relationship types without the APOC plugin, deliberately not
# added here). Index needed for the ~50M node scale target's seed-entity
# lookup (case-insensitive exact match on `name_key`) to stay fast.
_INDEX_CYPHER = (
    "CREATE INDEX entity_domain_namekey IF NOT EXISTS "
    "FOR (e:Entity) ON (e.domain_id, e.name_key)"
)


@lru_cache
def get_graph_client():
    # Deferred import -- same reason as chunking/embeddings.py's
    # get_embedding_model()/extraction/extractor.py's get_extractor_model():
    # keeps this module importable in contexts that never touch Neo4j
    # (e.g. local sqlite-based tests) without the driver installed.
    from langchain_neo4j import Neo4jGraph

    settings = get_settings()
    graph = Neo4jGraph(
        url=settings.neo4j_uri,
        username=settings.neo4j_user,
        password=settings.neo4j_password,
        refresh_schema=False,
    )
    graph.query(_INDEX_CYPHER)
    return graph
