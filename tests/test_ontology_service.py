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


def _bare_node(name: str) -> dict:
    # A node_types entry with no description/threshold set, as stored --
    # matches NodeTypeSpec.model_dump() for a name-only declaration.
    return {"name": name, "description": None, "threshold": None}


def _bare_relation(name: str, source_type: str, target_type: str) -> dict:
    return {
        "name": name, "source_type": source_type, "target_type": target_type,
        "description": None, "threshold": None,
    }


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
    assert schema.node_types == [_bare_node("Person"), _bare_node("Company")]
    assert schema.relation_types == [_bare_relation("works_at", "Person", "Company")]


def test_create_schema_version_strips_whitespace(db_session, monkeypatch):
    _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)

    schema = service.create_schema_version(
        db_session, domain.id,
        models.OntologySchemaCreate(node_types=[" Person ", "Company"]),
        uuid4(),
    )

    assert schema.node_types == [_bare_node("Person"), _bare_node("Company")]


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

    assert schema.node_types == [_bare_node("Person"), _bare_node("Company")]
    assert schema.relation_types == [_bare_relation("works_at", "Person", "Company")]


def test_import_schema_from_yaml_rejects_invalid_yaml(db_session):
    domain = _make_domain(db_session)

    with pytest.raises(InvalidOntologySchemaError):
        service.import_schema_from_yaml(db_session, domain.id, b"not: valid: yaml: [", uuid4())


def test_import_schema_from_yaml_rejects_wrong_shape(db_session):
    domain = _make_domain(db_session)

    with pytest.raises(InvalidOntologySchemaError):
        service.import_schema_from_yaml(db_session, domain.id, b"- just\n- a\n- list\n", uuid4())


def test_create_schema_version_persists_node_type_description_and_threshold(db_session, monkeypatch):
    # The actual "ontology matches the document's semantic content" fix:
    # a domain admin can ground an abstract type name (here "role") in
    # what it actually means for their domain, and tighten its
    # confidence bar independently of every other type -- see
    # extraction/extractor.py for where this gets used against the real
    # model.
    _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)

    schema = service.create_schema_version(
        db_session, domain.id,
        models.OntologySchemaCreate(node_types=[
            {
                "name": "role",
                "description": "  A named job title held by a specific person, not a system component.  ",
                "threshold": 0.8,
            },
            "person",  # bare string still allowed alongside a rich spec
        ]),
        uuid4(),
    )

    assert schema.node_types == [
        {
            "name": "role",
            "description": "A named job title held by a specific person, not a system component.",
            "threshold": 0.8,
        },
        _bare_node("person"),
    ]


def test_create_schema_version_persists_relation_type_description_and_threshold(db_session, monkeypatch):
    _stub_reextraction(monkeypatch)
    domain = _make_domain(db_session)

    schema = service.create_schema_version(
        db_session, domain.id,
        models.OntologySchemaCreate(
            node_types=["technology", "requirement"],
            relation_types=[{
                "name": "used_for", "source_type": "technology", "target_type": "requirement",
                "description": "The source technology explicitly implements the target requirement.",
                "threshold": 0.7,
            }],
        ),
        uuid4(),
    )

    assert schema.relation_types == [{
        "name": "used_for", "source_type": "technology", "target_type": "requirement",
        "description": "The source technology explicitly implements the target requirement.",
        "threshold": 0.7,
    }]
