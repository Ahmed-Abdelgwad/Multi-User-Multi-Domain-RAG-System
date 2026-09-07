"""Thin wrapper around gliner2's JointIE model (spec 2.5): loaded once per
worker process (module-level lazy singleton, same shape as
chunking/embeddings.py) since instantiating it is expensive and each
worker only ever needs one copy. `fastino/gliner2-multi-v1` is pinned
project-wide -- see the plan's Context section for why: same JointIE
joint entity+relation extraction in one forward pass as the `2.5-multi`
variant originally pinned here and the same multilingual (mDeBERTa-based,
per the model's own maintainer) coverage this project needs, but 205M
params vs. that variant's 287M -- switched to this smaller checkpoint
after this host's tight RAM made the larger model's live load
slow/fragile (see the plan's Phase 7 Progress entry), without giving up
multilingual support, which is a real project requirement, not optional.

`gliner2` is imported lazily inside `get_extractor_model()`, not at
module level, so importing this module from the API process (via
extraction/service.py -> controller.py, for the read-only graph
endpoints) never pulls in torch/transformers -- same rationale as
chunking/embeddings.py keeping sentence_transformers out of its top-level
imports.
"""
from dataclasses import dataclass, field
from functools import lru_cache

EXTRACTOR_MODEL_NAME = "fastino/gliner2-multi-v1"

# Below this confidence, an entity or relation is more likely model noise
# than a real assertion -- same filtering idea as ingestion/extraction.py's
# MIN_TABLE_ACCURACY for Camelot tables. Applied to *both* entities and
# relations -- an asymmetric first version filtered only relations,
# leaving low-confidence entity noise (stray punctuation, section
# headers) through unfiltered; found live against a real, bullet-list-
# heavy CV where that noise was actually visible in the resulting graph.
MIN_ENTITY_CONFIDENCE = 0.5
MIN_RELATION_CONFIDENCE = 0.5


def _has_alnum(text: str) -> bool:
    """True if `text` contains at least one letter/digit. Confirmed live
    (not assumed) against a real CV: a lone bullet character ("▸",
    bleeding in from the source PDF's list markup right next to a
    section like "EXPERIENCE") gets tagged type=person by the model at
    **0.76-0.81 confidence** -- comfortably above MIN_ENTITY_CONFIDENCE,
    so the confidence filter alone never touches it. Raising the
    threshold to clear it would also cut real entities sitting in the
    same band (e.g. "LangGraph" at 0.67, "vector databases" at 0.64) --
    the wrong trade. This is a genuine model-quality miss, not a
    threshold-tuning problem, so it needs its own narrow rule: an entity
    with no alphanumeric content at all is never a real named entity
    regardless of the model's confidence in it.
    """
    return any(ch.isalnum() for ch in text)


@dataclass(frozen=True)
class ExtractedEntity:
    type: str
    name: str


@dataclass(frozen=True)
class ExtractedTriple:
    subject: ExtractedEntity
    predicate: str
    object: ExtractedEntity


@dataclass(frozen=True)
class ExtractionOutput:
    entities: list[ExtractedEntity] = field(default_factory=list)
    triples: list[ExtractedTriple] = field(default_factory=list)


@lru_cache
def get_extractor_model():
    from gliner2.joint_ie import JointIE
    return JointIE.from_pretrained(EXTRACTOR_MODEL_NAME)


def extractor_model_version() -> str:
    return EXTRACTOR_MODEL_NAME


def extract(text: str, node_types: list[str], relation_types: list[dict]) -> ExtractionOutput:
    """Runs JointIE against `text`, constrained to the given ontology
    schema (`node_types`: list[str]; `relation_types`:
    list[{"name", "source_type", "target_type"}] -- straight off
    `OntologySchema`, see ontology/models.py's `RelationTypeSpec`).
    `JointIE`'s own schema builder guarantees every emitted relation
    already conforms to a declared type pair, so no separate validation
    pass is needed here on the model's output -- only a confidence filter.
    """
    if not text.strip() or not node_types:
        return ExtractionOutput()

    model = get_extractor_model()
    schema = model.create_schema().entities(node_types)
    for relation in relation_types:
        schema = schema.relation(relation["name"], relation["source_type"], relation["target_type"])

    result = model.extract(text, schema)
    if not result.feasible:
        return ExtractionOutput()

    entities_by_id = {
        entity.id: ExtractedEntity(type=entity.type, name=entity.text)
        for entity in result.entities
        if entity.confidence >= MIN_ENTITY_CONFIDENCE and _has_alnum(entity.text)
    }

    triples: list[ExtractedTriple] = []
    for relation in result.relations:
        if relation.confidence < MIN_RELATION_CONFIDENCE:
            continue
        head = entities_by_id.get(relation.head)
        tail = entities_by_id.get(relation.tail)
        if not head or not tail:
            continue
        triples.append(ExtractedTriple(subject=head, predicate=relation.type, object=tail))

    return ExtractionOutput(entities=list(entities_by_id.values()), triples=triples)
