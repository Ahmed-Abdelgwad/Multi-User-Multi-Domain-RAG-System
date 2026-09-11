from sqlalchemy import Column, Float, JSON, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base
from .enums import LLMRoute


class DomainRetrievalConfig(Base):
    """Spec 3.4/3.5/3.6's "configurable per domain" knobs, one row per
    domain rather than three separate config tables: RRF signal weights
    (3.4), LLM routing rule (3.5), and confidence threshold (3.6).
    """

    __tablename__ = 'domain_retrieval_configs'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey('domains.id'), nullable=False, unique=True)

    dense_weight = Column(Float, nullable=False, default=1.0)
    bm25_weight = Column(Float, nullable=False, default=1.0)
    graph_weight = Column(Float, nullable=False, default=1.0)

    # 3.4's entity-centric routing rule, per domain (was a hardcoded
    # module constant in router.py -- flagged as a partial-compliance
    # gap and closed here).
    entity_centric_ratio_threshold = Column(Float, nullable=False, default=0.3)
    entity_centric_graph_boost = Column(Float, nullable=False, default=2.0)

    llm_routing_default = Column(Enum(LLMRoute), nullable=False, default=LLMRoute.API)
    llm_routing_sensitive_keywords = Column(JSON, nullable=False, default=list)

    confidence_threshold = Column(Float, nullable=False, default=0.5)

    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<DomainRetrievalConfig(domain_id='{self.domain_id}')>"
