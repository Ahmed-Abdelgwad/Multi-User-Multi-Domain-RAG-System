from dataclasses import dataclass, field
from functools import lru_cache

EXTRACTOR_MODEL_NAME = "fastino/gliner2-multi-v1"


MIN_ENTITY_CONFIDENCE = 0.5
MIN_RELATION_CONFIDENCE = 0.5


def _as_type_spec(entry) -> dict:
    
    if isinstance(entry, str):
        return {"name": entry, "description": None, "threshold": None}
    return {"name": entry["name"], "description": entry.get("description"), "threshold": entry.get("threshold")}


def _has_alnum(text: str) -> bool:
    
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


def extract(text: str, node_types: list, relation_types: list[dict]) -> ExtractionOutput:
    
    if not text.strip() or not node_types:
        return ExtractionOutput()

    node_specs = [_as_type_spec(n) for n in node_types]

    model = get_extractor_model()
    schema = model.create_schema()
    for node in node_specs:
        schema = schema.entity(node["name"], description=node["description"], threshold=node["threshold"])
    for relation in relation_types:
        schema = schema.relation(
            relation["name"], relation["source_type"], relation["target_type"],
            description=relation.get("description"), threshold=relation.get("threshold"),
        )

    result = model.extract(text, schema)
    if not result.feasible:
        return ExtractionOutput()

    # A per-type `threshold` (set on the ontology's node/relation type)
    # overrides the global MIN_*_CONFIDENCE default for that type only --
    # lets an admin raise the bar for one noise-prone type without
    # affecting every other type in the same ontology.
    entity_thresholds = {n["name"]: n["threshold"] for n in node_specs}
    relation_thresholds = {r["name"]: r.get("threshold") for r in relation_types}

    entities_by_id = {}
    for entity in result.entities:
        threshold = entity_thresholds.get(entity.type)
        threshold = threshold if threshold is not None else MIN_ENTITY_CONFIDENCE
        if entity.confidence < threshold or not _has_alnum(entity.text):
            continue
        entities_by_id[entity.id] = ExtractedEntity(type=entity.type, name=entity.text)

    triples: list[ExtractedTriple] = []
    for relation in result.relations:
        threshold = relation_thresholds.get(relation.type)
        threshold = threshold if threshold is not None else MIN_RELATION_CONFIDENCE
        if relation.confidence < threshold:
            continue
        head = entities_by_id.get(relation.head)
        tail = entities_by_id.get(relation.tail)
        if not head or not tail:
            continue
        triples.append(ExtractedTriple(subject=head, predicate=relation.type, object=tail))

    return ExtractionOutput(entities=list(entities_by_id.values()), triples=triples)
