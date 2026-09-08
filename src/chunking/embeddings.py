from functools import lru_cache
from langchain_core.embeddings import Embeddings
from ..config import get_settings


EMBEDDING_DIM = 384


@lru_cache
def get_embedding_model():
    
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().embedding_model_name)


def embed_texts(texts: list[str]) -> list[list[float]]:
    
    if not texts:
        return []
    model = get_embedding_model()
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vectors.tolist()


def embedding_model_version() -> str:

    return get_settings().embedding_model_name


class SentenceTransformerEmbeddings(Embeddings):
    
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        return embed_texts([text])[0]
