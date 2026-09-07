"""create chunk graph node/edge links

Revision ID: 0012_chunk_graph_links
Revises: 0011_create_graph_nodes_edges
Create Date: 2026-09-06 00:00:00.000003

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012_chunk_graph_links'
down_revision: Union[str, Sequence[str], None] = '0011_create_graph_nodes_edges'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('chunk_graph_node_links',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('chunk_id', sa.UUID(), nullable=False),
    sa.Column('graph_node_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['chunk_id'], ['chunks.id'], ),
    sa.ForeignKeyConstraint(['graph_node_id'], ['graph_nodes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('chunk_id', 'graph_node_id', name='uq_chunk_graph_node_links_pair'),
    )
    op.create_index('ix_chunk_graph_node_links_chunk_id', 'chunk_graph_node_links', ['chunk_id'])
    op.create_index('ix_chunk_graph_node_links_graph_node_id', 'chunk_graph_node_links', ['graph_node_id'])

    op.create_table('chunk_graph_edge_links',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('chunk_id', sa.UUID(), nullable=False),
    sa.Column('graph_edge_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['chunk_id'], ['chunks.id'], ),
    sa.ForeignKeyConstraint(['graph_edge_id'], ['graph_edges.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('chunk_id', 'graph_edge_id', name='uq_chunk_graph_edge_links_pair'),
    )
    op.create_index('ix_chunk_graph_edge_links_chunk_id', 'chunk_graph_edge_links', ['chunk_id'])
    op.create_index('ix_chunk_graph_edge_links_graph_edge_id', 'chunk_graph_edge_links', ['graph_edge_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chunk_graph_edge_links_graph_edge_id', table_name='chunk_graph_edge_links')
    op.drop_index('ix_chunk_graph_edge_links_chunk_id', table_name='chunk_graph_edge_links')
    op.drop_table('chunk_graph_edge_links')
    op.drop_index('ix_chunk_graph_node_links_graph_node_id', table_name='chunk_graph_node_links')
    op.drop_index('ix_chunk_graph_node_links_chunk_id', table_name='chunk_graph_node_links')
    op.drop_table('chunk_graph_node_links')
