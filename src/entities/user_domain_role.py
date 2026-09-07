from sqlalchemy import Column, ForeignKey, DateTime, Enum, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base
from .enums import DomainRole


class UserDomainRole(Base):
    __tablename__ = 'user_domain_roles'
    __table_args__ = (
        UniqueConstraint('user_id', 'domain_id', name='uq_user_domain_roles_user_domain'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    domain_id = Column(UUID(as_uuid=True), ForeignKey('domains.id'), nullable=False)
    role = Column(Enum(DomainRole), nullable=False)
    granted_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    granted_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<UserDomainRole(user_id='{self.user_id}', domain_id='{self.domain_id}', role={self.role})>"
