"""evaluation result

Spec 4.1-4.3/4.6's judge output + human-override fields, one row per
query_logs row.

Revision ID: 0022_evaluation_result
Revises: 0021_query_log
Create Date: 2026-09-14 00:00:00.000003

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0022_evaluation_result'
down_revision: Union[str, Sequence[str], None] = '0021_query_log'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    evaluation_status = sa.Enum('PENDING', 'COMPLETED', 'FAILED', 'SKIPPED', name='evaluationstatus')
    # A distinct type from `llmroute` -- judge_provider answers "which
    # model judged this," not "which model generated it" -- named by
    # actual provider (MERCURY/OLLAMA), not an abstract local/api tier.
    judge_provider_enum = sa.Enum('MERCURY', 'OLLAMA', name='judgeprovider')

    op.create_table('evaluation_results',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('query_log_id', sa.UUID(), nullable=False),
    sa.Column('status', evaluation_status, nullable=False),
    sa.Column('faithfulness', sa.Float(), nullable=True),
    sa.Column('relevance', sa.Float(), nullable=True),
    sa.Column('completeness', sa.Float(), nullable=True),
    sa.Column('citation_accuracy', sa.Float(), nullable=True),
    sa.Column('rationale', sa.JSON(), nullable=True),
    sa.Column('flagged', sa.Boolean(), nullable=False),
    sa.Column('judge_provider', judge_provider_enum, nullable=True),
    sa.Column('judge_model_version', sa.String(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('overridden_by', sa.UUID(), nullable=True),
    sa.Column('override_rationale', sa.Text(), nullable=True),
    sa.Column('overridden_at', sa.DateTime(), nullable=True),
    sa.Column('original_scores', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['query_log_id'], ['query_logs.id'], ),
    sa.ForeignKeyConstraint(['overridden_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('query_log_id', name='uq_evaluation_results_query_log_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # drop_table's own DDL drops both freshly-created enum types
    # (`evaluationstatus`, `judgeprovider`) automatically -- same
    # auto-drop behavior as every other enum in this project, since
    # neither used create_type=False (both are genuinely owned by this
    # table, unlike 0021's reuse of the pre-existing `llmroute` type).
    op.drop_table('evaluation_results')
