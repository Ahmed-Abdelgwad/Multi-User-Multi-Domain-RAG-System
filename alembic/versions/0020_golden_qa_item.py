"""golden qa item

Spec 4.5's curated golden Q&A set, domain-scoped. No dependency on
query_logs/evaluation_results (those reference this table, not the
other way around), so this lands first among the section-4 migrations.

Revision ID: 0020_golden_qa_item
Revises: 0019_session_policy_singleton
Create Date: 2026-09-14 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0020_golden_qa_item'
down_revision: Union[str, Sequence[str], None] = '0019_session_policy_singleton'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('golden_qa_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('domain_id', sa.UUID(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('expected_answer', sa.Text(), nullable=False),
    sa.Column('expected_citations', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('golden_qa_items')
