from functools import lru_cache
from src.config import get_settings


@lru_cache
def get_ner_model():
    """Load and cache the spaCy NER model for query analysis."""
    import spacy

    return spacy.load(get_settings().query_ner_model_name)


def analyze_query(query: str) -> tuple[list[tuple[str, str]], float]:
    

    doc = get_ner_model()(query)
    entities = [(ent.text, ent.label_) for ent in doc.ents]
    entity_token_ratio = (sum(len(ent) for ent in doc.ents) / len(doc)) if len(doc) else 0.0
    return entities, entity_token_ratio
