"""create ontology schemas

Revision ID: 0009_create_ontology_schemas
Revises: 0008_domain_ingestion_config
Create Date: 2026-09-06 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# NOTE: alembic_version.version_num is VARCHAR(32) -- keep revision ids
# at or under that length (this one is 29 chars).
revision: str = '0009_create_ontology_schemas'
down_revision: Union[str, Sequence[str], None] = '0008_domain_ingestion_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ontology_schemas',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('domain_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('node_types', sa.JSON(), nullable=False),
    sa.Column('relation_types', sa.JSON(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ontology_schemas_domain_id', 'ontology_schemas', ['domain_id'])
    # Partial unique index: DB-level guarantee that at most one version is
    # ever active per domain, on top of the app-level
    # deactivate-then-insert logic in ontology/service.py -- closes the
    # race window between two concurrent `create_schema_version` calls for
    # the same domain, which the app-level check alone can't.
    op.create_index(
        'uq_ontology_schemas_one_active_per_domain',
        'ontology_schemas',
        ['domain_id'],
        unique=True,
        postgresql_where=sa.text('is_active = true'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_ontology_schemas_one_active_per_domain', table_name='ontology_schemas')
    op.drop_index('ix_ontology_schemas_domain_id', table_name='ontology_schemas')
    op.drop_table('ontology_schemas')
