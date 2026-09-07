"""document tables_extracted

Revision ID: 0006_document_tables_extracted
Revises: 0005_create_documents
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# NOTE: alembic_version.version_num is VARCHAR(32) -- keep revision ids
# at or under that length (this one is 30 chars).
revision: str = '0006_document_tables_extracted'
down_revision: Union[str, Sequence[str], None] = '0005_create_documents'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('documents', sa.Column('tables_extracted', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('documents', 'tables_extracted')
