"""chunk content type add figure

Revision ID: 0025_chunk_content_type_figure
Revises: 0024_eval_human_verdict
Create Date: 2026-09-17 00:00:00.000001

Adds `FIGURE` to the `chunkcontenttype` enum, alongside `TEXT`/`TABLE`.
Vector-drawn charts (matplotlib-style figures embedded in a PDF, not a
raster image) decode as a flat run of axis/legend numbers with no
positional link back to which config/metric each belongs to -- confirmed
live against a real paper's Figure 4 ("100% 50% 0% 98% 50% 0%"), which
caused a query about one metric to be answered with a different table's
numbers instead. `extraction.py`'s new figure-block detection tags such
paragraphs (plus their adjacent "Figure N:" caption, if present) as one
atomic `content_type=FIGURE` chunk -- same never-split/never-merged
treatment as a Camelot table -- so the caption and its numbers travel
together through chunking instead of being scattered across a normal PGC
group boundary.

`ALTER TYPE ... ADD VALUE` cannot run in the same transaction as a
statement that *uses* the new value, but this migration only adds it,
so it's safe to run as a normal upgrade step.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0025_chunk_content_type_figure'
down_revision: Union[str, Sequence[str], None] = '0024_eval_human_verdict'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE chunkcontenttype ADD VALUE IF NOT EXISTS 'FIGURE' AFTER 'TABLE'")


def downgrade() -> None:
    """Downgrade schema.

    Postgres has no `DROP VALUE` for enums -- removing one requires
    rebuilding the type (create new type, cast the column, drop the old
    type), which risks data loss if any row is currently `FIGURE`. Left
    as a documented no-op, same posture as migration 0013's INDEXING
    addition.
    """
    pass
