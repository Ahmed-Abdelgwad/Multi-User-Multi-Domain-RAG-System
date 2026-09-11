from functools import lru_cache
from src.config import get_settings


@lru_cache
def get_ner_model():
    # Deferred import + lazy singleton, same pattern as the embedding /
    # extractor model loaders. spaCy's xx_ent_wiki_sm is multilingual,
    # ner-only (spec 3.3).
    #
    # FLAGGED SPEC DEVIATION: 3.3 literally asks for "shared self-hosted
    # model used at both ingestion and query time." This project uses
    # gliner2-multi-v1 at ingestion (needs its JointIE entity+relation
    # capability, per 2.5) and spaCy here at query time -- not shared.
    # Kept deliberately unshared after weighing it against live evidence
    # from this exact host: the `api` process already saturates swap
    # with just the embedding model loaded (see docker-compose.yml's
    # celery_worker/neo4j comments); gliner2 took 55+ minutes to
    # first-load in Phase 7 and is a much heavier per-call cost than
    # spaCy's NER-only pass. Loading it synchronously into every /query
    # request would very likely make this host unusable and regress the
    # ~1s warm latency measured in Phase 5. Revisit if this ever runs on
    # a host with real headroom.
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
