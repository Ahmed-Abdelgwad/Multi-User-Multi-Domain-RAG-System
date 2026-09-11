from functools import lru_cache
from ..config import get_settings

# Deferred imports (langchain_openai/langchain_ollama are Docker-only,
# not on the host) -- same pattern as get_embedding_model/get_extractor_model.


@lru_cache
def get_api_chat_model():
    """3.5's API tier: OpenRouter, OpenAI-compatible. Granite 4.2 is a
    hybrid reasoning model -- live-tested it burns 1.5k-3k hidden
    reasoning tokens (15-36s) on trivial answers unless reasoning is
    explicitly disabled via extra_body; with it off, same answers land
    in ~1-4s. api_key comes from OPENROUTER_API_KEY (Settings/env only,
    never hardcoded).
    """
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    return ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        model=settings.openrouter_model_name,
        api_key=settings.openrouter_api_key,
        temperature=0.2,
        extra_body={"reasoning": {"enabled": False}},
    )


@lru_cache
def get_local_chat_model():
    """3.5's local/internal tier. qwen3 also ships hybrid thinking mode --
    unverified here whether it needs the same disabling as Granite's
    reasoning flag above; check live latency once Ollama + the model are
    actually running before trusting this tier's response time.
    """
    from langchain_ollama import ChatOllama

    settings = get_settings()
    return ChatOllama(base_url=settings.ollama_base_url, model=settings.local_llm_model_name, temperature=0.2)
