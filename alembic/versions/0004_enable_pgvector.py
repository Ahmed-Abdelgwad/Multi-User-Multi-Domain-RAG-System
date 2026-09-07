"""enable pgvector extension

Revision ID: 0004_enable_pgvector
Revises: 0003_create_domains_and_roles
Create Date: 2026-08-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0004_enable_pgvector'
down_revision: Union[str, Sequence[str], None] = '0003_create_domains_and_roles'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Vector columns (Chunk.embedding, added in a later migration) need
    # this. SQLite has no extension mechanism and is only used for local
    # dev without Docker (see README) -- skip there rather than fail, so
    # that workflow keeps working; pgvector-backed features simply aren't
    # available under SQLite.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP EXTENSION IF EXISTS vector")
