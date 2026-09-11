from collections import Counter
from uuid import UUID
from pydantic import ConfigDict
from sqlalchemy.orm import Session
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from src.entities.chunk import Chunk
from src.authz.retrieval import attach_domain_provenance
from src.graph.client import get_graph_client

# Spec 3.2's graph signal: seed entities from query-time NER (3.3),
# case-insensitive exact match into the graph, 1-hop expansion capped at
# NEIGHBOR_LIMIT relations -- per paper 2's algorithm, re-implemented as
# genuine parameterized Cypher (see graph_store.py for the schema this
# reads: generic :Entity/:RELATES, domain guarded on both sides so
# cross-domain traversal is blocked by construction).
NEIGHBOR_LIMIT = 150

_SEED_AND_EXPAND = """
MATCH (seed:Entity)
WHERE seed.name_key = $name_key AND seed.domain_id IN $domain_ids
OPTIONAL MATCH (seed)-[r:RELATES]-(neighbor:Entity)
WHERE neighbor.domain_id IN $domain_ids
WITH seed, collect(DISTINCT r)[0..$neighbor_limit] AS rels, collect(DISTINCT neighbor)[0..$neighbor_limit] AS neighbors
RETURN seed.chunk_ids AS seed_chunk_ids,
       [rel IN rels | rel.chunk_ids] AS rel_chunk_ids_lists,
       [n IN neighbors | n.chunk_ids] AS neighbor_chunk_ids_lists
"""


class Neo4jGraphChunkRetriever(BaseRetriever):
    """Spec 3.2's graph signal. `entities` comes from 3.3's query-time
    NER -- construction alone (an empty list) means no Cypher runs at
    all, matching "graph retrieval activated by query-time NER output."
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    db: Session
    permitted_domain_ids: list[UUID]
    entities: list[tuple[str, str]]
    k: int = 5

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        if not self.entities:
            return []

        domain_ids = [str(d) for d in self.permitted_domain_ids]
        graph = get_graph_client()
        chunk_match_count: Counter[str] = Counter()

        for entity_text, _entity_type in self.entities:
            rows = graph.query(_SEED_AND_EXPAND, {
                "name_key": entity_text.strip().lower(),
                "domain_ids": domain_ids,
                "neighbor_limit": NEIGHBOR_LIMIT,
            })
            for row in rows:
                for chunk_id in row["seed_chunk_ids"] or []:
                    chunk_match_count[chunk_id] += 1
                for chunk_ids in row["rel_chunk_ids_lists"] or []:
                    for chunk_id in chunk_ids or []:
                        chunk_match_count[chunk_id] += 1
                for chunk_ids in row["neighbor_chunk_ids_lists"] or []:
                    for chunk_id in chunk_ids or []:
                        chunk_match_count[chunk_id] += 1

        if not chunk_match_count:
            return []

        top_chunk_ids = [UUID(cid) for cid, _ in chunk_match_count.most_common(self.k)]
        # Re-check domain permission against Postgres, the source of
        # truth for RBAC -- never trust a Neo4j property alone.
        rows = (
            self.db.query(Chunk)
            .filter(Chunk.id.in_(top_chunk_ids), Chunk.domain_id.in_(self.permitted_domain_ids))
            .all()
        )
        chunks_by_id = {chunk.id: chunk for chunk in rows}
        max_count = max(chunk_match_count.values())

        domain_names = {
            domain_id: attach_domain_provenance(domain_id, self.db).domain_name
            for domain_id in {chunk.domain_id for chunk in rows}
        }

        documents = []
        for chunk_id in top_chunk_ids:
            chunk = chunks_by_id.get(chunk_id)
            if not chunk:
                continue
            documents.append(Document(
                page_content=chunk.content,
                metadata={
                    "chunk_id": str(chunk.id),
                    "domain_id": str(chunk.domain_id),
                    "domain_name": domain_names[chunk.domain_id],
                    "content_type": chunk.content_type.value,
                    "graph_score": chunk_match_count[str(chunk_id)] / max_count,
                },
            ))
        return documents
