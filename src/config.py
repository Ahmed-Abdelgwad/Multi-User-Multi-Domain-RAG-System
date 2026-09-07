from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "197b2c37c391bed93fe80344fe73b806947a65e36206e05a1a23c2fa12702fe3"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    database_url: str = "postgresql://postgres:postgres@db:5432/cleanfastapi"

    oidc_internal_discovery_url: str | None = None
    oidc_internal_client_id: str | None = None
    oidc_internal_client_secret: str | None = None

    oidc_external_discovery_url: str | None = None
    oidc_external_client_id: str | None = None
    oidc_external_client_secret: str | None = None

    sso_redirect_base_url: str = "http://localhost:8000"
    saml_enabled: bool = False

    # Section 2: async pipeline (Celery/Redis)
    redis_url: str = "redis://redis:6379/0"

    # Section 2: object storage (MinIO / S3-compatible)
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "documents"
    minio_secure: bool = False

    # Section 2.4: chunk embedding model. Fixed once for the whole project
    # (spec 2.4 -- changing it means re-embedding every existing chunk), so
    # this exists as a documented override point, not something meant to
    # differ between dev/prod. ibm-granite/granite-embedding-97m-multilingual-r2
    # (~400-500MB RAM, 384-dim, Apache 2.0) was picked over BAAI/bge-m3
    # (~2.2GB RAM, 1024-dim) because this host measured only ~1.1GB RAM
    # available with swap already full when Phase 3 was implemented, and
    # it benchmarks as the strongest open multilingual retrieval model
    # under 100M params -- see chunking/embeddings.py.
    embedding_model_name: str = "ibm-granite/granite-embedding-97m-multilingual-r2"

    # Section 2.5: how often (seconds) `batch_extract_entities_task` sweeps
    # for chunks needing entity/relation extraction. Deliberately not
    # instant -- the plan's canonical 2.5 text accepts the graph lagging
    # the vector index "by one job cycle" for MVP, so this doesn't need to
    # be short; kept low enough (5 min) to make live verification practical.
    entity_extraction_batch_interval_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
