"""Spec 3.4: entity-centric ratio threshold + graph boost, per domain
(was hardcoded in router.py -- closes a "routing rules configurable per
domain" partial-compliance gap).

Revision ID: 0017_retrieval_entity_centric (kept <=32 chars -- alembic_version.version_num
is VARCHAR(32); see 0006's Progress note for the same constraint hitting a prior migration)
Revises: 0016_chunks_embedding_ann_index
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = '0017_retrieval_entity_centric'
down_revision: Union[str, Sequence[str], None] = '0016_chunks_embedding_ann_index'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'domain_retrieval_configs',
        sa.Column('entity_centric_ratio_threshold', sa.Float(), nullable=False, server_default='0.3'),
    )
    op.add_column(
        'domain_retrieval_configs',
        sa.Column('entity_centric_graph_boost', sa.Float(), nullable=False, server_default='2.0'),
    )


def downgrade() -> None:
    op.drop_column('domain_retrieval_configs', 'entity_centric_graph_boost')
    op.drop_column('domain_retrieval_configs', 'entity_centric_ratio_threshold')
