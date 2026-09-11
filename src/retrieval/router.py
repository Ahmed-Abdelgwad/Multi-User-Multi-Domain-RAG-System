from uuid import UUID
from sqlalchemy.orm import Session
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from src.entities.domain_retrieval_config import DomainRetrievalConfig
from .vector_retriever import PgVectorChunkRetriever
from .graph_retriever import Neo4jGraphChunkRetriever
from .bm25_retriever import get_bm25_retriever

# Spec 3.4 query routing. A query whose named-entity tokens cover at
# least this fraction of the query is treated as "factual / entity-
# centric" and the graph signal is boosted over the domain's configured
# weight; below it (but still some entities) is "mixed"; no entities is
# "semantic / open-ended" and the graph signal is left out entirely
# (spec 3.3: graph retrieval is *activated by* query-time NER output).
ENTITY_CENTRIC_RATIO_THRESHOLD = 0.3
ENTITY_CENTRIC_GRAPH_BOOST = 2.0


def select_retrievers_and_weights(
    db: Session,
    entities: list[tuple[str, str]],
    entity_token_ratio: float,
    permitted_domain_ids: list[UUID],
    config: DomainRetrievalConfig,
    k: int = 5,
) -> tuple[list[BaseRetriever], list[float]]:
    retrievers: list[BaseRetriever] = [
        PgVectorChunkRetriever(db=db, permitted_domain_ids=permitted_domain_ids, k=k)
    ]
    weights: list[float] = [config.dense_weight]

    bm25 = get_bm25_retriever(db, permitted_domain_ids, k=k)
    if bm25 is not None:
        retrievers.append(bm25)
        weights.append(config.bm25_weight)

    if entities:
        retrievers.append(Neo4jGraphChunkRetriever(
            db=db, permitted_domain_ids=permitted_domain_ids, entities=entities, k=k
        ))
        graph_weight = config.graph_weight
        if entity_token_ratio >= ENTITY_CENTRIC_RATIO_THRESHOLD:
            graph_weight *= ENTITY_CENTRIC_GRAPH_BOOST
        weights.append(graph_weight)

    return retrievers, weights


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_confidence(documents: list[Document], graph_activated: bool) -> float:
    """Spec 3.6: top-k chunk similarity, blended 50/50 with graph match
    strength where graph retrieval was activated.
    """
    vector_scores = [d.metadata["vector_score"] for d in documents if "vector_score" in d.metadata]
    vec = sum(vector_scores) / len(vector_scores) if vector_scores else 0.0
    if not graph_activated:
        return _clamp(vec)

    graph_scores = [d.metadata["graph_score"] for d in documents if "graph_score" in d.metadata]
    grf = sum(graph_scores) / len(graph_scores) if graph_scores else 0.0
    return _clamp(0.5 * vec + 0.5 * grf)
