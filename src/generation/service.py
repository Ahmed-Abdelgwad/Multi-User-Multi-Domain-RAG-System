import logging
from langchain_core.documents import Document
from src.entities.domain_retrieval_config import DomainRetrievalConfig
from src.entities.enums import LLMRoute
from src.config import get_settings
from src.exceptions import GenerationUnavailableError
from . import llm

LOCAL_UNAVAILABLE_MESSAGE = "Local generation model is not available on this host."


def classify_llm_route(query: str, config: DomainRetrievalConfig) -> LLMRoute:
    """Spec 3.5's routing rule: any configured sensitive keyword present
    in the query forces the local tier; otherwise the domain's default.
    """
    query_lower = query.lower()
    if any(keyword.lower() in query_lower for keyword in config.llm_routing_sensitive_keywords):
        return LLMRoute.LOCAL
    return config.llm_routing_default


def _format_context(documents: list[Document]) -> str:
    return "\n".join(f"[{i + 1}] {doc.page_content}" for i, doc in enumerate(documents))


def generate_answer(query: str, documents: list[Document], config: DomainRetrievalConfig) -> tuple[str, LLMRoute]:
    """3.5: route (local vs API), then answer strictly from the fused
    context documents, citing them inline as [1], [2].
    """
    route = classify_llm_route(query, config)

    if route == LLMRoute.LOCAL and not get_settings().local_llm_enabled:
        # RAM-safety default: local tier is a real, exercised code path,
        # not a raised exception -- flip local_llm_enabled once Ollama is
        # confirmed to fit this host.
        return LOCAL_UNAVAILABLE_MESSAGE, route

    chat_model = llm.get_local_chat_model() if route == LLMRoute.LOCAL else llm.get_api_chat_model()

    system_prompt = (
        "Answer the question using ONLY the numbered context passages below. "
        "Cite the passages you rely on inline as [1], [2]. If the passages don't "
        "contain the answer, say so plainly instead of guessing. "
        "Give your answer once, directly and concisely -- do not restate, "
        "repeat, or re-summarize it afterward.\n\n"
        f"Context:\n{_format_context(documents)}"
    )
    try:
        response = chat_model.invoke([("system", system_prompt), ("human", query)])
    except Exception as e:
        logging.warning(f"Generation failed via {route.value} route: {e}")
        raise GenerationUnavailableError(f"Generation via the '{route.value}' route failed") from e

    return response.content, route
