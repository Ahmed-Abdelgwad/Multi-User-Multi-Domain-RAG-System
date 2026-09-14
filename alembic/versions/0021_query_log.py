"""query log

Spec 4.3's "audit log ... alongside the answer record" -- the minimal
persistence anchor section 4 needs. `llmroute` enum already exists
(created by 0015_domain_retrieval_config) -- reused via create_type=False.

Real gotcha found live (new territory for this project -- every prior
enum reuse was single-table): generic `sa.Enum(..., create_type=False)`
silently drops the flag on this SQLAlchemy version (2.0.52) -- it
accepts the kwarg but `visit_enum`'s dialect-adapted impl still issues
CREATE TYPE, so `alembic upgrade head` failed live with
`DuplicateObject: type "llmroute" already exists`. `create_type` is
only honored on `sqlalchemy.dialects.postgresql.ENUM` directly (a quick
container-side check confirmed: the generic `sa.Enum` instance doesn't
even expose a `.create_type` attribute, while `postgresql.ENUM` does).

Revision ID: 0021_query_log
Revises: 0020_golden_qa_item
Create Date: 2026-09-14 00:00:00.000002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PGEnum


revision: str = '0021_query_log'
down_revision: Union[str, Sequence[str], None] = '0020_golden_qa_item'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    llm_route = PGEnum('LOCAL', 'API', name='llmroute', create_type=False)

    op.create_table('query_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('domain_ids', sa.JSON(), nullable=False),
    sa.Column('query', sa.Text(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=False),
    sa.Column('route', llm_route, nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('sources', sa.JSON(), nullable=False),
    sa.Column('graph_context', sa.JSON(), nullable=False),
    sa.Column('golden_qa_item_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['golden_qa_item_id'], ['golden_qa_items.id'], ),
    sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('query_logs')
