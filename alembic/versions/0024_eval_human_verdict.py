"""evaluation result human verdict

Spec 4.6's "accept or reject flagged answers" -- a moderation verdict on
the answer's overall usability, independent of (and combinable with) a
numeric score correction via the existing override fields.

Revision ID: 0024_eval_human_verdict
Revises: 0023_domain_eval_config
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0024_eval_human_verdict'
down_revision: Union[str, Sequence[str], None] = '0023_domain_eval_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

human_verdict_enum = sa.Enum('ACCEPTED', 'REJECTED', name='humanverdict')


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    # ADD COLUMN needs the enum TYPE to exist first on Postgres (unlike
    # CREATE TABLE, which creates it implicitly) -- same pattern as
    # 0002_extend_users_for_identity's user_type/auth_provider columns.
    human_verdict_enum.create(bind, checkfirst=True)

    with op.batch_alter_table('evaluation_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('human_verdict', human_verdict_enum, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('evaluation_results', schema=None) as batch_op:
        batch_op.drop_column('human_verdict')

    bind = op.get_bind()
    human_verdict_enum.drop(bind, checkfirst=True)
