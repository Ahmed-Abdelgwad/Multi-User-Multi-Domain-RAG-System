"""create documents

Revision ID: 0005_create_documents
Revises: 0004_enable_pgvector
Create Date: 2026-08-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005_create_documents'
down_revision: Union[str, Sequence[str], None] = '0004_enable_pgvector'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('domain_id', sa.UUID(), nullable=False),
    sa.Column('source_type', sa.Enum('PDF', 'DOCX', 'CSV', 'XLSX', 'WEB', 'DB', name='documentsourcetype'), nullable=False),
    sa.Column('filename', sa.String(), nullable=False),
    sa.Column('content_type', sa.String(), nullable=True),
    sa.Column('storage_key', sa.String(), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'PROCESSING', 'READY', 'FAILED', name='documentstatus'), nullable=False),
    sa.Column('error_message', sa.String(), nullable=True),
    sa.Column('ocr_used', sa.Boolean(), nullable=False),
    sa.Column('author', sa.String(), nullable=True),
    sa.Column('doc_created_at', sa.DateTime(), nullable=True),
    sa.Column('extracted_text', sa.Text(), nullable=True),
    sa.Column('uploaded_by', sa.UUID(), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_documents_domain_id', 'documents', ['domain_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_documents_domain_id', table_name='documents')
    op.drop_table('documents')
