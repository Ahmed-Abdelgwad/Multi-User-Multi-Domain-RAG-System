"""Spec 3.1: ANN search on the vector store, not exact brute-force.

`vector_ip_ops` matches vector_retriever.py's `max_inner_product` ordering
(embeddings are pre-normalized, so inner product == cosine similarity).
Plain `CREATE INDEX` (not CONCURRENTLY) since Alembic runs inside a
transaction and this project's chunk counts are still small enough that a
brief write-lock during creation is a non-issue -- revisit with
CONCURRENTLY (needs autocommit, outside Alembic's transaction) if/when
that stops being true.

Revision ID: 0016_chunks_embedding_ann_index
Revises: 0015_domain_retrieval_config
"""
from typing import Sequence, Union
from alembic import op

revision: str = '0016_chunks_embedding_ann_index'
down_revision: Union[str, Sequence[str], None] = '0015_domain_retrieval_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_ip_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
