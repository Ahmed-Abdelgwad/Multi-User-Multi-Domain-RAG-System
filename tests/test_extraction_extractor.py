"""Unit tests for extraction/extractor.py's own logic (schema building,
confidence filtering, result parsing) -- every other test in this
project stubs `extractor.extract()` wholesale, so this module's own
logic (not just its callers') had no coverage until now. A fake model
object stands in for the real `JointIE` instance, shaped exactly like
its documented API (`.create_schema().entity(name, description=,
threshold=).relation(name, source, target, description=, threshold=)`,
`.extract(text, schema)` -> an object with `.feasible`/`.entities`/
`.relations`, each entity/relation carrying `.id`/`.type`/`.text`/
`.confidence` or `.head`/`.tail`/`.type`/`.confidence`) -- confirmed
directly against `gliner2/joint_ie/schema.py`'s `JointSchema.entity`/
`.relation` signatures, not guessed.
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
    def __init__(self):
        self.entities_declared: list[dict] = []
        self.relations_declared: list[dict] = []

    def entity(self, name, description=None, *, threshold=None):
        self.entities_declared.append({"name": name, "description": description, "threshold": threshold})
        return self

    def relation(self, name, source_type, target_type, description=None, *, threshold=None):
        self.relations_declared.append({
            "name": name, "source_type": source_type, "target_type": target_type,
            "description": description, "threshold": threshold,
        })
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

    assert model.built_schema.entities_declared == [
        {"name": "person", "description": None, "threshold": None},
        {"name": "organization", "description": None, "threshold": None},
    ]
    assert model.built_schema.relations_declared == [{
        "name": "works_at", "source_type": "person", "target_type": "organization",
        "description": None, "threshold": None,
    }]


def test_extract_passes_node_type_description_and_threshold_to_schema(monkeypatch):
    # The actual fix for "ontology forces unrelated entities into
    # unsupported types" (found live: a bare "role" type run against a
    # non-narrative document got forced onto system nouns like "API
    # server"): a per-type `description` grounds the abstract type name
    # in what it means for this domain, passed straight through to
    # JointIE's own schema builder rather than kept only for display.
    model = _stub_model(monkeypatch, _FakeResult())

    extractor.extract(
        "text",
        [{
            "name": "role",
            "description": "A named job title held by a specific person, not a system component.",
            "threshold": 0.8,
        }],
        [],
    )

    assert model.built_schema.entities_declared == [{
        "name": "role",
        "description": "A named job title held by a specific person, not a system component.",
        "threshold": 0.8,
    }]


def test_extract_accepts_mixed_bare_strings_and_rich_specs(monkeypatch):
    # Most domains won't bother with descriptions for every type -- a
    # plain name and a full spec must be usable side by side in the same
    # ontology, and legacy schema versions (predating this feature) are
    # still bare strings throughout.
    model = _stub_model(monkeypatch, _FakeResult())

    extractor.extract("text", ["person", {"name": "role", "description": "A job title."}], [])

    assert model.built_schema.entities_declared == [
        {"name": "person", "description": None, "threshold": None},
        {"name": "role", "description": "A job title.", "threshold": None},
    ]


def test_extract_per_type_threshold_overrides_global_default(monkeypatch):
    # A type declared with its own `threshold` uses that bar instead of
    # MIN_ENTITY_CONFIDENCE -- lets an admin raise the bar for one
    # noise-prone type without affecting every other type in the same
    # ontology.
    _stub_model(monkeypatch, _FakeResult(entities=[
        _FakeEntity("e1", "role", "Domain Admin", confidence=0.6),  # above global default, below override
        _FakeEntity("e2", "person", "Alice", confidence=0.6),  # above global default, no override on this type
    ]))

    output = extractor.extract("text", [
        {"name": "role", "threshold": 0.9},
        {"name": "person"},
    ], [])

    assert [e.name for e in output.entities] == ["Alice"]


def test_extract_per_relation_threshold_overrides_global_default(monkeypatch):
    _stub_model(monkeypatch, _FakeResult(
        entities=[_FakeEntity("e1", "person", "Alice"), _FakeEntity("e2", "organization", "Acme")],
        relations=[_FakeRelation(head="e1", tail="e2", type="used_for", confidence=0.6)],
    ))

    output = extractor.extract("text", ["person", "organization"], [
        {"name": "used_for", "source_type": "person", "target_type": "organization", "threshold": 0.9},
    ])

    assert output.triples == []


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
