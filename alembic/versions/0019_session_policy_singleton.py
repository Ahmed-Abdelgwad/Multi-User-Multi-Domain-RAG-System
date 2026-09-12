"""session policy singleton enforcement

`0018_session_policy` created the table with only app-level (query-then-
insert) singleton behavior -- a real race on the very first concurrent
logins after deployment (before any row exists) could leave two rows,
after which .first() becomes non-deterministic. This adds the actual
DB-level guarantee: `singleton` is always true, and a UNIQUE constraint
on it means Postgres can never store a second row.

Revision ID: 0019_session_policy_singleton
Revises: 0018_session_policy
Create Date: 2026-09-12 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# NOTE: alembic_version.version_num is VARCHAR(32) -- this id is 29 chars.
revision: str = '0019_session_policy_singleton'
down_revision: Union[str, Sequence[str], None] = '0018_session_policy'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOT NULL + server_default backfills the existing row (there is at
    # most one, since app-level get_or_create already enforced that in
    # practice) to `true` as part of the same ALTER.
    op.add_column('session_policy', sa.Column('singleton', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_check_constraint('ck_session_policy_singleton_true', 'session_policy', 'singleton')
    op.create_unique_constraint('uq_session_policy_singleton', 'session_policy', ['singleton'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_session_policy_singleton', 'session_policy', type_='unique')
    op.drop_constraint('ck_session_policy_singleton_true', 'session_policy', type_='check')
    op.drop_column('session_policy', 'singleton')
