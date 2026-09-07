from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class Domain(Base):
    __tablename__ = 'domains'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)
    is_archived = Column(Boolean, nullable=False, default=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    archived_at = Column(DateTime, nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)

    def __repr__(self):
        return f"<Domain(name='{self.name}', is_archived={self.is_archived})>"
