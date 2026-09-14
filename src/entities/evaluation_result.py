from sqlalchemy import Column, String, Text, Float, Boolean, JSON, DateTime, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base
from .enums import EvaluationStatus, JudgeProvider


class EvaluationResult(Base):
    """Spec 4.1/4.2's judge output, one row per `QueryLog`. Created
    eagerly at `status=PENDING` the instant the async judge task starts
    (see tasks/pipeline.py::evaluate_query_log) so a polling client never
    has to distinguish "not started" from "still running" -- every path
    the task can take (success, provider failure, provider disabled)
    ends in an explicit terminal `status`, never an implicit one.

    4.6's human-override fields live here too rather than in a separate
    table -- one override event per answer is the realistic MVP shape,
    and `original_scores` preserves the judge's own call underneath it.
    """

    __tablename__ = 'evaluation_results'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_log_id = Column(UUID(as_uuid=True), ForeignKey('query_logs.id'), nullable=False, unique=True)

    status = Column(Enum(EvaluationStatus), nullable=False, default=EvaluationStatus.PENDING)

    faithfulness = Column(Float, nullable=True)
    relevance = Column(Float, nullable=True)
    completeness = Column(Float, nullable=True)
    citation_accuracy = Column(Float, nullable=True)
    rationale = Column(JSON, nullable=True)
    flagged = Column(Boolean, nullable=False, default=False)

    judge_provider = Column(Enum(JudgeProvider), nullable=True)
    judge_model_version = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)

    # Spec 4.6: human-in-the-loop override, logged only (no judge
    # fine-tuning from this data in MVP scope).
    overridden_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    override_rationale = Column(Text, nullable=True)
    overridden_at = Column(DateTime, nullable=True)
    original_scores = Column(JSON, nullable=True)

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<EvaluationResult(query_log_id='{self.query_log_id}', status={self.status})>"
