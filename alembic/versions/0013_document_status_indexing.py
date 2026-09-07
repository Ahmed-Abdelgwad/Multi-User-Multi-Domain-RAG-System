"""document status add indexing

Revision ID: 0013_document_status_indexing
Revises: 0012_chunk_graph_links
Create Date: 2026-09-07 03:00:00.000001

Adds `INDEXING` to the `documentstatus` enum, between `PROCESSING` and
`READY` -- see the plan's Progress entry for why: a document used to flip
to READY the moment text extraction finished, before chunking+embedding
(chained asynchronously right after) had actually run, so a client
polling status=="ready" could see zero chunks for the several seconds
until chunk_and_embed_task finished -- confirmed live against a real,
table-heavy document (18s gap, 0 chunks visible at "ready"). Now
PROCESSING->INDEXING happens at the end of text extraction, and
INDEXING->READY happens at the end of chunk_and_embed -- so "ready"
means "usable for retrieval" for the first time, matching what a
polling client actually needs.

`ALTER TYPE ... ADD VALUE` cannot run in the same transaction as a
statement that *uses* the new value, but this migration only adds it,
so it's safe to run as a normal upgrade step.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0013_document_status_indexing'
down_revision: Union[str, Sequence[str], None] = '0012_chunk_graph_links'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE documentstatus ADD VALUE IF NOT EXISTS 'INDEXING' AFTER 'PROCESSING'")


def downgrade() -> None:
    """Downgrade schema.

    Postgres has no `DROP VALUE` for enums -- removing one requires
    rebuilding the type (create new type, cast the column, drop the old
    type), which risks data loss if any row is currently `INDEXING`.
    Left as a documented no-op, same posture as other irreversible-enum
    situations; a real rollback would need a hand-written data migration.
    """
    pass
