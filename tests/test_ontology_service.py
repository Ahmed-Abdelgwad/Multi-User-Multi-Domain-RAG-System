from uuid import uuid4
import pytest
from src.entities.domain import Domain
from src.entities.ontology_schema import OntologySchema
from src.exceptions import InvalidOntologySchemaError, OntologySchemaNotFoundError
from src.ontology import service, models


def _make_domain(db_session) -> Domain:
    domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4())
    db_session.add(domain)
    db_session.commit()
    return domain


def _stub_reextraction(monkeypatch):
    """Unit tests only exercise the ontology service, not Celery -- stub
    the enqueue call so it never tries to reach a real broker.
    """
    calls = []
    monkeypatch.setattr(service, "_enqueue_reextraction", lambda domain_id: calls.append(domain_id))
    return calls


def test_create_schema_version_starts_at_one(db_session, monkeypatch):
    _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)

    schema = service.create_schema_version(
        db_session, domain.id,
        models.OntologySchemaCreate(node_types=["Person", "Company"], relation_types=[
            {"name": "works_at", "source_type": "Person", "target_type": "Company"},
        ]),
        uuid4(),
    )

    assert schema.version == 1
    assert schema.is_active is True
    assert schema.node_types == ["Person", "Company"]
    assert schema.relation_types == [{"name": "works_at", "source_type": "Person", "target_type": "Company"}]


def test_create_schema_version_strips_whitespace(db_session, monkeypatch):
    _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)

    schema = service.create_schema_version(
        db_session, domain.id,
        models.OntologySchemaCreate(node_types=[" Person ", "Company"]),
        uuid4(),
    )

    assert schema.node_types == ["Person", "Company"]


def test_create_schema_version_deactivates_previous_and_increments(db_session, monkeypatch):
    _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)

    first = service.create_schema_version(
        db_session, domain.id, models.OntologySchemaCreate(node_types=["Person"]), uuid4()
    )
    second = service.create_schema_version(
        db_session, domain.id, models.OntologySchemaCreate(node_types=["Person", "Company"]), uuid4()
    )

    db_session.refresh(first)
    assert first.is_active is False
    assert second.version == 2
    assert second.is_active is True

    active_count = (
        db_session.query(OntologySchema)
        .filter(OntologySchema.domain_id == domain.id, OntologySchema.is_active.is_(True))
        .count()
    )
    assert active_count == 1


def test_create_schema_version_enqueues_reextraction(db_session, monkeypatch):
    calls = _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)

    service.create_schema_version(db_session, domain.id, models.OntologySchemaCreate(node_types=["Person"]), uuid4())

    assert calls == [domain.id]


def test_create_schema_version_rejects_duplicate_node_types(db_session, monkeypatch):
    _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)

    with pytest.raises(InvalidOntologySchemaError):
        service.create_schema_version(
            db_session, domain.id, models.OntologySchemaCreate(node_types=["Person", "Person"]), uuid4()
        )


def test_create_schema_version_rejects_relation_with_undeclared_type(db_session, monkeypatch):
    _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)

    with pytest.raises(InvalidOntologySchemaError):
        service.create_schema_version(
            db_session, domain.id,
            models.OntologySchemaCreate(node_types=["Person"], relation_types=[
                {"name": "works_at", "source_type": "Person", "target_type": "Company"},
            ]),
            uuid4(),
        )


def test_create_schema_version_rejects_duplicate_relation_types(db_session, monkeypatch):
    _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)

    with pytest.raises(InvalidOntologySchemaError):
        service.create_schema_version(
            db_session, domain.id,
            models.OntologySchemaCreate(node_types=["Person", "Company"], relation_types=[
                {"name": "works_at", "source_type": "Person", "target_type": "Company"},
                {"name": "works_at", "source_type": "Person", "target_type": "Company"},
            ]),
            uuid4(),
        )


def test_get_active_schema_or_raise_no_schema_yet(db_session):
    domain = _make_domain(db_session)

    with pytest.raises(OntologySchemaNotFoundError):
        service.get_active_schema_or_raise(db_session, domain.id)


def test_get_active_schema_returns_the_active_one(db_session, monkeypatch):
    _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)
    service.create_schema_version(db_session, domain.id, models.OntologySchemaCreate(node_types=["Person"]), uuid4())
    second = service.create_schema_version(
        db_session, domain.id, models.OntologySchemaCreate(node_types=["Person", "Company"]), uuid4()
    )

    active = service.get_active_schema_or_raise(db_session, domain.id)

    assert active.id == second.id


def test_list_schema_versions_returns_all_in_order(db_session, monkeypatch):
    _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)
    service.create_schema_version(db_session, domain.id, models.OntologySchemaCreate(node_types=["Person"]), uuid4())
    service.create_schema_version(
        db_session, domain.id, models.OntologySchemaCreate(node_types=["Person", "Company"]), uuid4()
    )

    versions = service.list_schema_versions(db_session, domain.id)

    assert [v.version for v in versions] == [1, 2]


def test_import_schema_from_yaml_parses_and_creates(db_session, monkeypatch):
    _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)
    raw_yaml = b"""
node_types:
  - Person
  - Company
relation_types:
  - name: works_at
    source_type: Person
    target_type: Company
"""

    schema = service.import_schema_from_yaml(db_session, domain.id, raw_yaml, uuid4())

    assert schema.node_types == ["Person", "Company"]
    assert schema.relation_types == [{"name": "works_at", "source_type": "Person", "target_type": "Company"}]


def test_import_schema_from_yaml_rejects_invalid_yaml(db_session):
    domain = _make_domain(db_session)

    with pytest.raises(InvalidOntologySchemaError):
        service.import_schema_from_yaml(db_session, domain.id, b"not: valid: yaml: [", uuid4())


def test_import_schema_from_yaml_rejects_wrong_shape(db_session):
    domain = _make_domain(db_session)

    with pytest.raises(InvalidOntologySchemaError):
        service.import_schema_from_yaml(db_session, domain.id, b"- just\n- a\n- list\n", uuid4())
