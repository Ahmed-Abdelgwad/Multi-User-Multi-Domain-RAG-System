from sqlalchemy import Column, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class DomainEvaluationConfig(Base):
    """Spec 4.3/4.4's "configurable per domain" knobs for the judge
    layer: the flagging threshold (4.3) and the quality-dashboard
    degradation-alert delta (4.4). Same one-row-per-domain shape as
    DomainIngestionConfig/DomainRetrievalConfig.
    """

    __tablename__ = 'domain_evaluation_configs'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey('domains.id'), nullable=False, unique=True)

    flag_threshold = Column(Float, nullable=False, default=0.5)
    degradation_alert_threshold = Column(Float, nullable=False, default=0.1)

    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<DomainEvaluationConfig(domain_id='{self.domain_id}')>"
