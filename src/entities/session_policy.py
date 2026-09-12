from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class SessionPolicy(Base):
    """Spec 1.1's "configurable session token TTL" -- a single global
    singleton row (sessions aren't domain-scoped), one TTL per user pool
    since internal/external users may reasonably need different session
    lengths. Bootstrapped from Settings.access_token_expire_minutes the
    first time it's read, then live-editable by a platform admin from
    then on -- same get_or_create pattern as every per-domain config in
    this project, just without a domain_id.

    `singleton` is always True and is the actual enforcement mechanism:
    a UNIQUE constraint on a column that a CHECK constraint pins to a
    single value means Postgres can never hold a second row, regardless
    of `id` -- get_or_create's own "query then insert if missing" is
    still susceptible to a race (two concurrent first-ever calls both
    seeing no row), so this is what makes the singleton real rather than
    a best-effort app-level convention.
    """

    __tablename__ = 'session_policy'
    __table_args__ = (
        CheckConstraint('singleton', name='ck_session_policy_singleton_true'),
        UniqueConstraint('singleton', name='uq_session_policy_singleton'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    singleton = Column(Boolean, nullable=False, default=True)
    internal_token_ttl_minutes = Column(Integer, nullable=False)
    external_token_ttl_minutes = Column(Integer, nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<SessionPolicy(internal={self.internal_token_ttl_minutes}m, external={self.external_token_ttl_minutes}m)>"
