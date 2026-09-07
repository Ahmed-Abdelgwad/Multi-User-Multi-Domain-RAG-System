"""Self-hosted embedding model wrapper (spec 2.4), loaded in-process
inside the Celery worker -- no separate model-serving microservice for
the MVP (see the section-2 plan's Architecture additions).

`sentence_transformers` (and the torch it pulls in) is imported lazily
inside `get_embedding_model()`, not at module import time -- this module
is imported by `chunking/service.py`, which is also imported by
`chunking/controller.py` for the config-CRUD and chunk-listing endpoints.
Those run in the API process and never need the model loaded; importing
torch there would burn RAM for nothing on an already RAM-constrained host.
"""
from functools import lru_cache
from ..config import get_settings

# Matches src/entities/chunk.py's EMBEDDING_DIM -- verified against the
# model's own Hugging Face page (ibm-granite/granite-embedding-97m-multilingual-r2),
# not assumed. Changing the model requires updating both and re-embedding
# every existing chunk (spec 2.4's versioning: old chunks stay `is_active`
# under their original `embedding_model_version` until the re-index completes).
EMBEDDING_DIM = 384


@lru_cache
def get_embedding_model():
    """Loaded once per worker process (module-level lazy singleton via
    lru_cache) -- loading it per-task would repeat a ~400-500MB model
    load on every chunk_and_embed task, which is both slow and wasteful
    on this RAM-constrained host.
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().embedding_model_name)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embeds a batch of chunk contents. Granite-embedding-r2 needs no
    query/passage instruction prefix (unlike e5-family models), so chunk
    text is encoded as-is. Embeddings are L2-normalized so pgvector's
    cosine-distance operator (`<=>`) behaves correctly at query time.
    """
    if not texts:
        return []
    model = get_embedding_model()
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vectors.tolist()


def embedding_model_version() -> str:
    """Stamped onto each Chunk row (`embedding_model_version`) so a future
    model swap can identify and re-embed chunks from a prior generation.
    """
    return get_settings().embedding_model_name
