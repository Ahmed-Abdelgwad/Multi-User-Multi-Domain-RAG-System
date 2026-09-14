"""domain evaluation config

Spec 4.3/4.4's per-domain flag threshold + degradation-alert delta.

Revision ID: 0023_domain_eval_config
Revises: 0022_evaluation_result
Create Date: 2026-09-14 00:00:00.000004

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0023_domain_eval_config'
down_revision: Union[str, Sequence[str], None] = '0022_evaluation_result'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('domain_evaluation_configs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('domain_id', sa.UUID(), nullable=False),
    sa.Column('flag_threshold', sa.Float(), nullable=False),
    sa.Column('degradation_alert_threshold', sa.Float(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('domain_id', name='uq_domain_evaluation_configs_domain_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('domain_evaluation_configs')
