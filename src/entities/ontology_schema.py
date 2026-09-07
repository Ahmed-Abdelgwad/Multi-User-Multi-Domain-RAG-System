from sqlalchemy import Column, Boolean, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from ..database.core import Base


class OntologySchema(Base):
    """A versioned, domain-scoped schema (spec 2.6) that constrains what
    Phase 7's extraction model is allowed to emit: `node_types` is a flat
    list[str] of allowed entity type names; `relation_types` is a
    list[{"name", "source_type", "target_type"}], each referencing a
    declared node type. Maps directly onto gliner2's `JointIE` schema
    builder (`.entities(node_types)` + `.relation(name, source_type,
    target_type)` per declared relation_type) with no translation layer.

    Only one version is ever `is_active` per domain at a time -- creating
    a new version deactivates the previous one in the same transaction
    (see ontology/service.py), so extraction always reads a single
    unambiguous active schema. Old versions are kept (not deleted) so
    `graph_node`/`graph_edge` rows can record which `ontology_version`
    produced them.
    """
    __tablename__ = 'ontology_schemas'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), ForeignKey('domains.id'), nullable=False)

    version = Column(Integer, nullable=False)
    node_types = Column(JSON, nullable=False)
    relation_types = Column(JSON, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<OntologySchema(domain_id='{self.domain_id}', version={self.version}, active={self.is_active})>"
