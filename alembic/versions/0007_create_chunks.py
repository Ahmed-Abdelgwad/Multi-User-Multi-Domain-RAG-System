"""create chunks

Revision ID: 0007_create_chunks
Revises: 0006_document_tables_extracted
Create Date: 2026-09-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
# NOTE: alembic_version.version_num is VARCHAR(32) -- keep revision ids
# at or under that length (this one is 19 chars).
revision: str = '0007_create_chunks'
down_revision: Union[str, Sequence[str], None] = '0006_document_tables_extracted'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Must match src/entities/chunk.py's EMBEDDING_DIM.
EMBEDDING_DIM = 384


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('domain_id', sa.UUID(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('content_type', sa.Enum('TEXT', 'TABLE', name='chunkcontenttype'), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('embedding', Vector(EMBEDDING_DIM), nullable=True),
    sa.Column('embedding_model_version', sa.String(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_chunks_document_id', 'chunks', ['document_id'])
    op.create_index('ix_chunks_domain_id', 'chunks', ['domain_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chunks_domain_id', table_name='chunks')
    op.drop_index('ix_chunks_document_id', table_name='chunks')
    op.drop_table('chunks')
