"""document elements_extracted

Revision ID: 0014_document_elements
Revises: 0013_document_status_indexing
Create Date: 2026-09-08 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0014_document_elements'
down_revision: Union[str, Sequence[str], None] = '0013_document_status_indexing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('documents', sa.Column('elements_extracted', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('documents', 'elements_extracted')
