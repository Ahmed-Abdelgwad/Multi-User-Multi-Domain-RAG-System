"""chunk entities extracted timestamp

Revision ID: 0010_chunk_entities_extracted
Revises: 0009_create_ontology_schemas
Create Date: 2026-09-06 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010_chunk_entities_extracted'
down_revision: Union[str, Sequence[str], None] = '0009_create_ontology_schemas'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('chunks', sa.Column('entities_extracted_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chunks', 'entities_extracted_at')
