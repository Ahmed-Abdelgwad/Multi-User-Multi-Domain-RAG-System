import logging
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from src.entities.ontology_schema import OntologySchema
from src.exceptions import InvalidOntologySchemaError, OntologySchemaNotFoundError
from . import models


def _validate_and_normalize(create: models.OntologySchemaCreate) -> tuple[list[str], list[models.RelationTypeSpec]]:
    node_types = [n.strip() for n in create.node_types]
    if any(not n for n in node_types):
        raise InvalidOntologySchemaError("node_types must not contain blank entries")
    if len(node_types) != len(set(node_types)):
        raise InvalidOntologySchemaError("node_types must not contain duplicates")

    node_type_set = set(node_types)
    relation_types: list[models.RelationTypeSpec] = []
    seen_relations: set[tuple[str, str, str]] = set()
    for relation in create.relation_types:
        name = relation.name.strip()
        source_type = relation.source_type.strip()
        target_type = relation.target_type.strip()
        if source_type not in node_type_set:
            raise InvalidOntologySchemaError(
                f"relation_type '{name}' references undeclared source_type '{source_type}'"
            )
        if target_type not in node_type_set:
            raise InvalidOntologySchemaError(
                f"relation_type '{name}' references undeclared target_type '{target_type}'"
            )
        key = (name, source_type, target_type)
        if key in seen_relations:
            raise InvalidOntologySchemaError(
                f"duplicate relation_type '{name}' ({source_type} -> {target_type})"
            )
        seen_relations.add(key)
        relation_types.append(models.RelationTypeSpec(name=name, source_type=source_type, target_type=target_type))

    return node_types, relation_types


def get_active_schema_or_raise(db: Session, domain_id: UUID) -> OntologySchema:
    schema = (
        db.query(OntologySchema)
        .filter(OntologySchema.domain_id == domain_id, OntologySchema.is_active.is_(True))
        .first()
    )
    if not schema:
        raise OntologySchemaNotFoundError(domain_id)
    return schema


def list_schema_versions(db: Session, domain_id: UUID) -> list[OntologySchema]:
    return (
        db.query(OntologySchema)
        .filter(OntologySchema.domain_id == domain_id)
        .order_by(OntologySchema.version)
        .all()
    )


def create_schema_version(
    db: Session, domain_id: UUID, create: models.OntologySchemaCreate, created_by: UUID
) -> OntologySchema:
    """Creates a new version and deactivates whatever was previously active,
    in the same transaction, so exactly one version is ever active per
    domain (extraction always reads a single unambiguous schema) -- also
    enforced at the DB level by a partial unique index on
    `(domain_id) WHERE is_active` (migration 0009), so a race between two
    concurrent admins can't leave two active versions. Old versions are
    kept, not deleted, so existing graph_node/graph_edge rows'
    `ontology_version` stamps stay resolvable.

    A new active version means every already-extracted graph_node/graph_edge
    in this domain was produced against a now-stale schema, so this also
    schedules a background re-extraction pass over the domain's ready
    documents (spec 2.5) -- enqueued via Celery, never run inline here,
    since re-running extraction for a whole domain can be slow and must
    not block this request/commit.
    """
    node_types, relation_types = _validate_and_normalize(create)

    previous_active = (
        db.query(OntologySchema)
        .filter(OntologySchema.domain_id == domain_id, OntologySchema.is_active.is_(True))
        .first()
    )
    next_version = (previous_active.version + 1) if previous_active else 1
    if previous_active:
        previous_active.is_active = False
        # Flushed before the new row is added: the partial unique index
        # (migration 0009) checks uniqueness per-statement, not deferred to
        # commit, so without this explicit ordering the new INSERT could
        # race SQLAlchemy's own flush ordering of the UPDATE and trip it.
        db.flush()

    schema = OntologySchema(
        id=uuid4(),
        domain_id=domain_id,
        version=next_version,
        node_types=node_types,
        relation_types=[r.model_dump() for r in relation_types],
        is_active=True,
        created_by=created_by,
    )
    db.add(schema)
    db.commit()
    db.refresh(schema)
    logging.info(f"Ontology schema v{next_version} created for domain {domain_id} by {created_by}")

    _enqueue_reextraction(domain_id)
    return schema


def _enqueue_reextraction(domain_id: UUID) -> None:
    # Imported lazily to avoid an ontology<->tasks import cycle, same
    # rationale as ingestion/service.py's `_enqueue_extraction`.
    from src.tasks.pipeline import reextract_domain_task
    reextract_domain_task.delay(str(domain_id))


def import_schema_from_yaml(
    db: Session, domain_id: UUID, raw_yaml: bytes, created_by: UUID
) -> OntologySchema:
    """Spec 2.6's YAML import: a domain admin hands over a schema as a
    file instead of typing it into the JSON body of `create_schema_version`
    directly. Expected shape:

        node_types: [Person, Company]
        relation_types:
          - {name: works_at, source_type: Person, target_type: Company}
    """
    import yaml

    try:
        parsed = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as e:
        raise InvalidOntologySchemaError(f"Invalid YAML: {e}")

    if not isinstance(parsed, dict):
        raise InvalidOntologySchemaError("YAML must be a mapping with 'node_types' and 'relation_types'")

    try:
        create = models.OntologySchemaCreate(**parsed)
    except Exception as e:
        raise InvalidOntologySchemaError(f"Invalid ontology schema: {e}")

    return create_schema_version(db, domain_id, create, created_by)
