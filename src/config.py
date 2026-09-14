from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

# Plain Literal here, not entities.enums.JudgeProvider -- importing the
# entities package from config.py would be circular (database/core.py,
# imported transitively by every entity module, itself imports
# get_settings from this file). Settings.judge_provider's value is cast
# to JudgeProvider at the one call site that needs it (evaluation/judge.py).


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

    
    embedding_model_name: str = "ibm-granite/granite-embedding-97m-multilingual-r2"

    entity_extraction_batch_interval_seconds: int = 300

    # Section 3: Retrieval, Ranking & Generation
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4jpassword"

    query_ner_model_name: str = "xx_ent_wiki_sm"
    bm25_cache_ttl_seconds: int = 600

    # 3.5 generation: OpenRouter for the API tier (external, hosted),
    # Ollama for the local tier (internal/sensitive queries).
    openrouter_api_key: str | None = None
    openrouter_model_name: str = "ibm-granite/granite-4.2-8b"
    local_llm_enabled: bool = False
    local_llm_model_name: str = "qwen3:4b"
    ollama_base_url: str = "http://ollama:11434"

    # Section 4: Judge LLM Evaluation Layer. Mercury 2.5 (Inception Labs)
    # is the default judge for ALL traffic today -- a deliberate MVP
    # choice, not routed by generation's LLMRoute yet (see
    # evaluation/judge.py's module docstring for the data-residency
    # caveat this implies). judge_provider is "mercury"/"ollama" (cast to
    # entities.enums.JudgeProvider at the call site), default "mercury"
    # -- flipping this one value is the whole migration path to an
    # all-local (Ollama) judge later.
    inception_api_key: str | None = None
    judge_api_model_name: str = "mercury-2.5"
    judge_api_reasoning_effort: str = "low"
    judge_provider: Literal["mercury", "ollama"] = "mercury"
    judge_llm_enabled: bool = False
    judge_llm_model_name: str = "qwen3:4b"
    golden_regression_cron_hour: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
