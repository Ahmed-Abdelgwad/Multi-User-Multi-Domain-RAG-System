"""extend users for identity

Revision ID: 0002_extend_users_for_identity
Revises: 0001_initial_baseline
Create Date: 2026-08-20 18:21:25.395248

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002_extend_users_for_identity'
down_revision: Union[str, Sequence[str], None] = '0001_initial_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

user_type_enum = sa.Enum('INTERNAL', 'EXTERNAL', name='usertype')
auth_provider_enum = sa.Enum('LOCAL', 'OIDC', 'SAML', name='authprovidertype')


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    # Postgres requires the enum TYPE to exist before it can be used in
    # ADD COLUMN (unlike CREATE TABLE, which creates it implicitly). No-op on
    # backends without a native enum type (e.g. sqlite).
    user_type_enum.create(bind, checkfirst=True)
    auth_provider_enum.create(bind, checkfirst=True)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'user_type', user_type_enum,
            nullable=False, server_default='INTERNAL',
        ))
        batch_op.add_column(sa.Column(
            'auth_provider', auth_provider_enum,
            nullable=False, server_default='LOCAL',
        ))
        batch_op.add_column(sa.Column('external_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column(
            'is_platform_admin', sa.Boolean(), nullable=False, server_default=sa.false(),
        ))
        batch_op.add_column(sa.Column(
            'is_active', sa.Boolean(), nullable=False, server_default=sa.true(),
        ))
        batch_op.alter_column('password_hash',
               existing_type=sa.VARCHAR(),
               nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('password_hash',
               existing_type=sa.VARCHAR(),
               nullable=False)
        batch_op.drop_column('is_active')
        batch_op.drop_column('is_platform_admin')
        batch_op.drop_column('external_id')
        batch_op.drop_column('auth_provider')
        batch_op.drop_column('user_type')

    bind = op.get_bind()
    auth_provider_enum.drop(bind, checkfirst=True)
    user_type_enum.drop(bind, checkfirst=True)
