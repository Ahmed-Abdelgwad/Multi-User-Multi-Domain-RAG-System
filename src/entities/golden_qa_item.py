from sqlalchemy import Column, Text, JSON, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class GoldenQAItem(Base):
    """Spec 4.5's curated golden Q&A set: a domain admin's known-good
    question/answer/citations, used as a reference-aware regression
    fixture (see evaluation/service.py::run_golden_regression_for_domain)
    rather than scored reference-free like a live query.
    """

    __tablename__ = 'golden_qa_items'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey('domains.id'), nullable=False)

    question = Column(Text, nullable=False)
    expected_answer = Column(Text, nullable=False)
    expected_citations = Column(JSON, nullable=False, default=list)

    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<GoldenQAItem(domain_id='{self.domain_id}', question='{self.question[:30]}')>"
