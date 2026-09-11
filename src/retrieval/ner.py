from functools import lru_cache
from src.config import get_settings


@lru_cache
def get_ner_model():
    # Deferred import + lazy singleton, same pattern as the embedding /
    # extractor model loaders. spaCy's xx_ent_wiki_sm is multilingual,
    # ner-only (spec 3.3) -- a deliberately lighter model than
    # ingestion's gliner2, chosen for the RAM-constrained api process.
    import spacy

    return spacy.load(get_settings().query_ner_model_name)


def analyze_query(query: str) -> tuple[list[tuple[str, str]], float]:
    """Spec 3.3: analyse an incoming query for named entities before
    retrieval. Returns (entities, entity_token_ratio) from one spaCy
    pass -- entities as (text, label) pairs, ratio = share of tokens
    covered by an entity span (0.0 for an empty/tokenless query),
    which the 3.4 router uses to weight graph retrieval.
    """
    doc = get_ner_model()(query)
    entities = [(ent.text, ent.label_) for ent in doc.ents]
    entity_token_ratio = (sum(len(ent) for ent in doc.ents) / len(doc)) if len(doc) else 0.0
    return entities, entity_token_ratio
