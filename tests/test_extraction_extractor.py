"""Unit tests for extraction/extractor.py's own logic (schema building,
confidence filtering, result parsing) -- every other test in this
project stubs `extractor.extract()` wholesale, so this module's own
logic (not just its callers') had no coverage until now. A fake model
object stands in for the real `JointIE` instance, shaped exactly like
its documented API (`.create_schema().entities([...]).relation(...)`,
`.extract(text, schema)` -> an object with `.feasible`/`.entities`/
`.relations`, each entity/relation carrying `.id`/`.type`/`.text`/
`.confidence` or `.head`/`.tail`/`.type`/`.confidence`).
"""
from dataclasses import dataclass, field
from src.extraction import extractor


@dataclass
class _FakeEntity:
    id: str
    type: str
    text: str
    confidence: float = 1.0


@dataclass
class _FakeRelation:
    head: str
    tail: str
    type: str
    confidence: float = 1.0


@dataclass
class _FakeResult:
    feasible: bool = True
    entities: list = field(default_factory=list)
    relations: list = field(default_factory=list)


class _FakeSchema:
    def entities(self, node_types):
        self.node_types = node_types
        return self

    def relation(self, name, source_type, target_type):
        self.relations_declared = getattr(self, "relations_declared", [])
        self.relations_declared.append((name, source_type, target_type))
        return self


class _FakeModel:
    def __init__(self, result: _FakeResult):
        self._result = result
        self.built_schema: _FakeSchema | None = None
        self.extract_calls: list = []

    def create_schema(self):
        return _FakeSchema()

    def extract(self, text, schema):
        self.built_schema = schema
        self.extract_calls.append(text)
        return self._result


def _stub_model(monkeypatch, result: _FakeResult) -> _FakeModel:
    model = _FakeModel(result)
    monkeypatch.setattr(extractor, "get_extractor_model", lambda: model)
    return model


def test_extract_returns_empty_for_blank_text(monkeypatch):
    model = _stub_model(monkeypatch, _FakeResult())

    output = extractor.extract("   ", ["person"], [])

    assert output.entities == []
    assert output.triples == []
    assert model.extract_calls == []  # never even called the model


def test_extract_returns_empty_when_infeasible(monkeypatch):
    _stub_model(monkeypatch, _FakeResult(feasible=False, entities=[_FakeEntity("e1", "person", "Alice")]))

    output = extractor.extract("Alice works at Acme.", ["person"], [])

    assert output.entities == []


def test_extract_builds_schema_from_ontology(monkeypatch):
    model = _stub_model(monkeypatch, _FakeResult())

    extractor.extract(
        "text", ["person", "organization"],
        [{"name": "works_at", "source_type": "person", "target_type": "organization"}],
    )

    assert model.built_schema.node_types == ["person", "organization"]
    assert model.built_schema.relations_declared == [("works_at", "person", "organization")]


def test_extract_filters_low_confidence_entities(monkeypatch):
    # Regression test: entities used to bypass confidence filtering
    # entirely (only relations were filtered) -- found live against a
    # real CV, where a genuinely low-confidence stray "entity" passed
    # straight through into the graph.
    _stub_model(monkeypatch, _FakeResult(entities=[
        _FakeEntity("e1", "person", "Alice", confidence=0.9),
        _FakeEntity("e2", "person", "Consulting", confidence=0.1),
    ]))

    output = extractor.extract("text", ["person"], [])

    assert [e.name for e in output.entities] == ["Alice"]


def test_extract_filters_punctuation_only_entities_regardless_of_confidence(monkeypatch):
    # Regression test for a second, distinct real bug found live against
    # the same CV: the model tagged a lone bullet character ("▸",
    # bleeding in from the source PDF's list markup) as type=person at
    # **0.76-0.81 confidence** -- comfortably above MIN_ENTITY_CONFIDENCE,
    # so the confidence filter alone never caught it. Confirmed by
    # temporarily logging raw model output against the real chunk rather
    # than assumed. Needs its own rule: no alphanumeric content at all
    # means it's never a real entity, independent of confidence.
    _stub_model(monkeypatch, _FakeResult(entities=[
        _FakeEntity("e1", "person", "Alice", confidence=0.9),
        _FakeEntity("e2", "person", "▸", confidence=0.81),
    ]))

    output = extractor.extract("text", ["person"], [])

    assert [e.name for e in output.entities] == ["Alice"]


def test_extract_filters_low_confidence_relations(monkeypatch):
    _stub_model(monkeypatch, _FakeResult(
        entities=[_FakeEntity("e1", "person", "Alice"), _FakeEntity("e2", "organization", "Acme")],
        relations=[_FakeRelation(head="e1", tail="e2", type="works_at", confidence=0.1)],
    ))

    output = extractor.extract("text", ["person", "organization"], [
        {"name": "works_at", "source_type": "person", "target_type": "organization"},
    ])

    assert output.triples == []
    assert [e.name for e in output.entities] == ["Alice", "Acme"]  # entities still kept


def test_extract_skips_relation_whose_endpoint_was_filtered_out(monkeypatch):
    # A relation can reference an entity that confidence-filtering just
    # dropped -- must be skipped, not KeyError.
    _stub_model(monkeypatch, _FakeResult(
        entities=[
            _FakeEntity("e1", "person", "Alice", confidence=0.9),
            _FakeEntity("e2", "organization", "Acme", confidence=0.1),  # filtered out
        ],
        relations=[_FakeRelation(head="e1", tail="e2", type="works_at", confidence=0.9)],
    ))

    output = extractor.extract("text", ["person", "organization"], [
        {"name": "works_at", "source_type": "person", "target_type": "organization"},
    ])

    assert output.triples == []
    assert [e.name for e in output.entities] == ["Alice"]


def test_extract_returns_correct_triples_for_feasible_result(monkeypatch):
    _stub_model(monkeypatch, _FakeResult(
        entities=[_FakeEntity("e1", "person", "Alice"), _FakeEntity("e2", "organization", "Acme")],
        relations=[_FakeRelation(head="e1", tail="e2", type="works_at", confidence=0.9)],
    ))

    output = extractor.extract("Alice works at Acme.", ["person", "organization"], [
        {"name": "works_at", "source_type": "person", "target_type": "organization"},
    ])

    assert len(output.triples) == 1
    triple = output.triples[0]
    assert triple.subject.name == "Alice"
    assert triple.predicate == "works_at"
    assert triple.object.name == "Acme"
