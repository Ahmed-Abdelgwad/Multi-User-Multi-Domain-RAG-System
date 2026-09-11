from uuid import UUID
from pydantic import ConfigDict
from sqlalchemy.orm import Session
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from src.entities.chunk import Chunk
from src.authz.retrieval import attach_domain_provenance
from src.chunking.embeddings import embed_texts


class PgVectorChunkRetriever(BaseRetriever):


    model_config = ConfigDict(arbitrary_types_allowed=True)

    db: Session
    permitted_domain_ids: list[UUID]
    k: int = 5

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        query_vector = embed_texts([query])[0]
        
        neg_inner_product = Chunk.embedding.max_inner_product(query_vector)

        rows = (
            self.db.query(Chunk, neg_inner_product.label("neg_inner_product"))
            .filter(Chunk.domain_id.in_(self.permitted_domain_ids), Chunk.is_active.is_(True))
            .order_by(neg_inner_product)
            .limit(self.k)
            .all()
        )

        # One provenance lookup per distinct domain among the results,
        # not per chunk -- attach_domain_provenance runs its own query.
        domain_names = {
            domain_id: attach_domain_provenance(domain_id, self.db).domain_name
            for domain_id in {chunk.domain_id for chunk, _ in rows}
        }

        return [
            Document(
                page_content=chunk.content,
                metadata={
                    "chunk_id": str(chunk.id),
                    "domain_id": str(chunk.domain_id),
                    "domain_name": domain_names[chunk.domain_id],
                    "content_type": chunk.content_type.value,
                    "vector_score": -neg_score,
                },
            )
            for chunk, neg_score in rows
        ]
