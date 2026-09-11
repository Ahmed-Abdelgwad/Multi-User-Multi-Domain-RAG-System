"""domain retrieval config

Revision ID: 0015_domain_retrieval_config
Revises: 0014_document_elements
Create Date: 2026-09-09 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# NOTE: alembic_version.version_num is VARCHAR(32) -- keep revision ids
# at or under that length (this one is 28 chars).
revision: str = '0015_domain_retrieval_config'
down_revision: Union[str, Sequence[str], None] = '0014_document_elements'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # No separate `.create()` call for the enum type -- op.create_table's
    # own DDL already creates any Enum type referenced by a column
    # (same as 0007_create_chunks.py's chunkcontenttype); calling
    # .create() first only causes a duplicate-type error when
    # create_table tries to create it again right after.
    llm_route = sa.Enum('LOCAL', 'API', name='llmroute')

    op.create_table('domain_retrieval_configs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('domain_id', sa.UUID(), nullable=False),
    sa.Column('dense_weight', sa.Float(), nullable=False),
    sa.Column('bm25_weight', sa.Float(), nullable=False),
    sa.Column('graph_weight', sa.Float(), nullable=False),
    sa.Column('llm_routing_default', llm_route, nullable=False),
    sa.Column('llm_routing_sensitive_keywords', sa.JSON(), nullable=False),
    sa.Column('confidence_threshold', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('domain_id', name='uq_domain_retrieval_configs_domain_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # drop_table's own DDL drops the llmroute enum type too (mirrors
    # create_table's auto-create) -- no separate drop call needed, same
    # reasoning as upgrade() above.
    op.drop_table('domain_retrieval_configs')
