"""domain ingestion config

Revision ID: 0008_domain_ingestion_config
Revises: 0007_create_chunks
Create Date: 2026-09-01 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# NOTE: alembic_version.version_num is VARCHAR(32) -- keep revision ids
# at or under that length (this one is 29 chars).
revision: str = '0008_domain_ingestion_config'
down_revision: Union[str, Sequence[str], None] = '0007_create_chunks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('domain_ingestion_configs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('domain_id', sa.UUID(), nullable=False),
    sa.Column('paragraphs_per_chunk', sa.Integer(), nullable=False),
    sa.Column('paragraph_overlap', sa.Integer(), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('domain_id', name='uq_domain_ingestion_configs_domain_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('domain_ingestion_configs')
