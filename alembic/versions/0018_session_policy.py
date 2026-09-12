"""session policy

Revision ID: 0018_session_policy
Revises: 0017_retrieval_entity_centric
Create Date: 2026-09-12 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# NOTE: alembic_version.version_num is VARCHAR(32) -- keep revision ids
# at or under that length (this one is 20 chars).
revision: str = '0018_session_policy'
down_revision: Union[str, Sequence[str], None] = '0017_retrieval_entity_centric'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Global singleton, no domain_id -- sessions aren't domain-scoped.
    op.create_table('session_policy',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('internal_token_ttl_minutes', sa.Integer(), nullable=False),
    sa.Column('external_token_ttl_minutes', sa.Integer(), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('session_policy')
