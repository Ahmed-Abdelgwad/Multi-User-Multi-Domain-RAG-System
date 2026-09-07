"""create graph nodes and edges

Revision ID: 0011_create_graph_nodes_edges
Revises: 0010_chunk_entities_extracted
Create Date: 2026-09-06 00:00:00.000002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011_create_graph_nodes_edges'
down_revision: Union[str, Sequence[str], None] = '0010_chunk_entities_extracted'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('graph_nodes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('domain_id', sa.UUID(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('name_key', sa.String(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('properties', sa.JSON(), nullable=True),
    sa.Column('ontology_version', sa.Integer(), nullable=False),
    sa.Column('extractor_model_version', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('domain_id', 'type', 'name_key', name='uq_graph_nodes_domain_type_name_key'),
    )
    op.create_index('ix_graph_nodes_domain_id', 'graph_nodes', ['domain_id'])

    op.create_table('graph_edges',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('domain_id', sa.UUID(), nullable=False),
    sa.Column('source_node_id', sa.UUID(), nullable=False),
    sa.Column('target_node_id', sa.UUID(), nullable=False),
    sa.Column('predicate', sa.String(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('mention_count', sa.Integer(), nullable=False),
    sa.Column('ontology_version', sa.Integer(), nullable=False),
    sa.Column('extractor_model_version', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ),
    sa.ForeignKeyConstraint(['source_node_id'], ['graph_nodes.id'], ),
    sa.ForeignKeyConstraint(['target_node_id'], ['graph_nodes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('domain_id', 'source_node_id', 'target_node_id', 'predicate', name='uq_graph_edges_triple'),
    )
    op.create_index('ix_graph_edges_domain_id', 'graph_edges', ['domain_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_graph_edges_domain_id', table_name='graph_edges')
    op.drop_table('graph_edges')
    op.drop_index('ix_graph_nodes_domain_id', table_name='graph_nodes')
    op.drop_table('graph_nodes')
