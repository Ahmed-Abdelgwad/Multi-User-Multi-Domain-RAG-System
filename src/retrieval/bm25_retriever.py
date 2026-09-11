import time
from uuid import UUID
from sqlalchemy.orm import Session
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from src.config import get_settings
from src.entities.chunk import Chunk
from src.authz.retrieval import attach_domain_provenance

# Spec 3.4 signal 2. In-memory BM25 over a domain set's active chunks,
# rebuilt wholesale on TTL expiry (not incrementally maintained) --
# fine at MVP chunk counts, a known cost at large domains, cache keyed
# by the sorted domain-id tuple.
_cache: dict[tuple[UUID, ...], tuple[float, BM25Retriever]] = {}


def _preprocess(text: str) -> list[str]:
    return text.lower().split()


def get_bm25_retriever(db: Session, domain_ids: list[UUID], k: int = 5) -> BM25Retriever | None:
    key = tuple(sorted(domain_ids))
    ttl = get_settings().bm25_cache_ttl_seconds
    cached = _cache.get(key)
    if cached and (time.monotonic() - cached[0]) < ttl:
        cached[1].k = k
        return cached[1]

    rows = (
        db.query(Chunk)
        .filter(Chunk.domain_id.in_(domain_ids), Chunk.is_active.is_(True))
        .all()
    )
    if not rows:
        return None

    domain_names = {
        domain_id: attach_domain_provenance(domain_id, db).domain_name
        for domain_id in {chunk.domain_id for chunk in rows}
    }
    docs = [
        Document(
            page_content=chunk.content,
            metadata={
                "chunk_id": str(chunk.id),
                "domain_id": str(chunk.domain_id),
                "domain_name": domain_names[chunk.domain_id],
                "content_type": chunk.content_type.value,
            },
        )
        for chunk in rows
    ]
    retriever = BM25Retriever.from_documents(docs, k=k, preprocess_func=_preprocess)
    _cache[key] = (time.monotonic(), retriever)
    return retriever
