from sqlalchemy import Column, Text, Float, JSON, DateTime, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base
from .enums import LLMRoute


class QueryLog(Base):
    """Spec 4.3's "audit log ... alongside the answer record" -- the
    minimal persistence anchor this section needs, deliberately scoped
    to exactly that (not the full spec 5.2 audit-log shape, same
    deliberate-minimalism call already made for /query itself).

    `golden_qa_item_id` is set only when this row was produced by 4.5's
    nightly regression run against a curated golden item, never by a
    real user query -- lets the quality dashboard/moderation-queue
    filter regression history out of (or into) live traffic with one
    `WHERE`, no separate table/UNION needed.
    """

    __tablename__ = 'query_logs'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    domain_ids = Column(JSON, nullable=False)

    query = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    route = Column(Enum(LLMRoute), nullable=False)
    confidence = Column(Float, nullable=False)

    sources = Column(JSON, nullable=False, default=list)
    graph_context = Column(JSON, nullable=False, default=list)

    golden_qa_item_id = Column(UUID(as_uuid=True), ForeignKey('golden_qa_items.id'), nullable=True)

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<QueryLog(user_id='{self.user_id}', route={self.route})>"
