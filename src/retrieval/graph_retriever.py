from collections import Counter, defaultdict
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
WITH seed, collect(DISTINCT {rel: r, neighbor: neighbor})[0..$neighbor_limit] AS pairs
RETURN seed.chunk_ids AS seed_chunk_ids,
       [p IN pairs | p.rel.chunk_ids] AS rel_chunk_ids_lists,
       [p IN pairs | p.neighbor.chunk_ids] AS neighbor_chunk_ids_lists,
       seed.type AS seed_type, seed.name AS seed_name,
       [p IN pairs | p.rel.predicate] AS rel_predicates,
       [p IN pairs | p.neighbor.type] AS neighbor_types,
       [p IN pairs | p.neighbor.name] AS neighbor_names
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
        # Spec 4.1's judge input needs "chunks + graph nodes" -- this
        # tracks which formatted Subject-Predicate-Object triples
        # actually support each chunk, so the retrieval/service.py
        # caller can surface them (previously these were computed here
        # and immediately discarded, only chunk_ids were kept).
        chunk_triples: dict[str, set[str]] = defaultdict(set)

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

                # Each index i across rel_predicates/neighbor_types/
                # neighbor_names/rel_chunk_ids_lists/neighbor_chunk_ids_lists
                # corresponds to one matched (relation, neighbor) pair --
                # collected together as {rel, neighbor} maps in Cypher
                # specifically so these lists stay index-aligned (two
                # independent DISTINCT collects would not guarantee that).
                pairs = zip(
                    row["rel_predicates"] or [],
                    row["neighbor_types"] or [],
                    row["neighbor_names"] or [],
                    row["rel_chunk_ids_lists"] or [],
                    row["neighbor_chunk_ids_lists"] or [],
                )
                for predicate, neighbor_type, neighbor_name, rel_chunk_ids, neighbor_chunk_ids in pairs:
                    if predicate is None:
                        continue  # OPTIONAL MATCH found no neighbor for this row
                    triple = f"{row['seed_type']}:{row['seed_name']} --{predicate}--> {neighbor_type}:{neighbor_name}"
                    for chunk_id in (rel_chunk_ids or []) + (neighbor_chunk_ids or []):
                        chunk_triples[chunk_id].add(triple)

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
                    "graph_triples": sorted(chunk_triples.get(str(chunk_id), set())),
                },
            ))
        return documents
