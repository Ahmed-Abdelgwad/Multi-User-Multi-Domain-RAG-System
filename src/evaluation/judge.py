"""Spec 4.1's Judge LLM Service. Mercury 2.5 (Inception Labs, API) is the
default judge for ALL traffic today, regardless of the generation
route -- a deliberate MVP choice, not a rewrite of 3.5's local/API
routing. `JudgeProvider` (entities/enums.py) is its own type, distinct
from generation's `LLMRoute`: it answers "which model judged this
answer," not "which model generated it."

MVP data-residency caveat, stated plainly: sending every answer's query
+ context + generated text to Mercury's API is a real exposure for any
domain that also configures `llm_routing_sensitive_keywords` on its
generation config -- the whole reason 3.5 keeps that content on the
LOCAL/self-hosted generation tier in the first place. Judging that same
content externally undercuts that guarantee. Accepted for now because
(1) Ollama has never been successfully verified running on this host,
so a Mercury-only default is what's actually deliverable and testable
today, and (2) nothing in this MVP's scope is real production data.
Before any production deployment handling genuinely sensitive/internal
content, this must be revisited -- either wire per-route judge
selection (the `provider` parameter below already supports it, just
unused by any call site yet) or force `judge_provider=ollama` globally
once Ollama is confirmed stable on this host.
"""
import logging
from functools import lru_cache
from langchain_core.documents import Document
from pydantic import BaseModel, Field
from src.config import get_settings
from src.entities.enums import JudgeProvider
from src.exceptions import JudgeUnavailableError

# Deferred imports (langchain_openai/langchain_ollama are Docker-only,
# not on the host) -- same pattern as generation/llm.py's two getters.


@lru_cache
def get_mercury_judge_model():
    """Live-verified against the real Inception API (see the plan file's
    "Model evaluation: Mercury 2.5" writeup): correctly discriminates a
    grounded answer (all four dimensions 1.0) from a corrupted one
    (faithfulness 0.25, citation_accuracy 0.0) with `reasoning_effort:
    "low"` -- cuts reasoning-token spend ~4x versus the default with no
    loss of discrimination.
    """
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    return ChatOpenAI(
        base_url="https://api.inceptionlabs.ai/v1",
        model=settings.judge_api_model_name,
        api_key=settings.inception_api_key,
        temperature=0.5,  # Mercury's diffusion sampling floor -- 0 is rejected.
        extra_body={"reasoning_effort": settings.judge_api_reasoning_effort},
    )


@lru_cache
def get_ollama_judge_model():
    """Implemented but not in the default flow (see module docstring) --
    kept RAM-safety-gated by `judge_llm_enabled` at the call site
    exactly like generation's own local tier.
    """
    from langchain_ollama import ChatOllama

    settings = get_settings()
    return ChatOllama(base_url=settings.ollama_base_url, model=settings.judge_llm_model_name, temperature=0.2)


class JudgeScores(BaseModel):
    """Spec 4.1's literal output shape: four 0-1 dimension scores plus a
    short rationale string per dimension.
    """
    faithfulness: float = Field(ge=0.0, le=1.0)
    faithfulness_rationale: str
    relevance: float = Field(ge=0.0, le=1.0)
    relevance_rationale: str
    completeness: float = Field(ge=0.0, le=1.0)
    completeness_rationale: str
    citation_accuracy: float = Field(ge=0.0, le=1.0)
    citation_accuracy_rationale: str


_JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator of RAG (retrieval-augmented generation) answers. "
    "You will be given a QUERY, numbered CONTEXT passages, optionally GRAPH FACTS "
    "(Subject-Predicate-Object triples the retrieval system matched), and a "
    "GENERATED ANSWER that cites context inline as [1], [2], etc. Score four "
    "dimensions from 0.0 to 1.0 each:\n"
    "- faithfulness: decompose the answer into atomic statements and check each "
    "one against the context/graph facts -- is every claim actually supported? "
    "Unsupported or contradicted claims should sharply lower this score.\n"
    "- relevance: is the retrieved context/graph facts actually relevant to the query?\n"
    "- completeness: does the answer cover the key information available in the "
    "context/graph facts that pertains to the query?\n"
    "- citation_accuracy: do the inline [n] citations actually point to context "
    "that supports the statement they are attached to (both correctness of "
    "existing citations and absence of missing ones)?\n"
    "For each dimension also give a one-sentence rationale naming what you found. "
    "Respond ONLY via the provided JSON schema."
)

_JUDGE_SYSTEM_PROMPT_WITH_REFERENCE = _JUDGE_SYSTEM_PROMPT + (
    "\n\nA REFERENCE ANSWER (and possibly REFERENCE CITATIONS) curated by a "
    "domain admin as ground truth is also provided. Judge more strictly with it "
    "in hand: faithfulness should also flag any contradiction with the reference, "
    "and completeness should be measured against the reference answer's key "
    "points specifically, not just the raw context."
)


def _format_context(documents: list[Document]) -> str:
    return "\n".join(f"[{i + 1}] {doc.page_content}" for i, doc in enumerate(documents))


def build_judge_prompt(
    query: str,
    documents: list[Document],
    graph_context: list[str],
    answer: str,
    reference: tuple[str, list[str]] | None = None,
) -> str:
    """`reference` is (expected_answer, expected_citations) from a golden
    Q&A item (spec 4.5's stricter regression mode) -- `None` for a live
    query, reference-free per RAGAS's core design premise.
    """
    parts = [f"QUERY: {query}", "", "CONTEXT:", _format_context(documents)]

    if graph_context:
        parts += ["", "GRAPH FACTS:"] + [f"- {triple}" for triple in graph_context]

    if reference:
        expected_answer, expected_citations = reference
        parts += ["", f"REFERENCE ANSWER: {expected_answer}"]
        if expected_citations:
            parts.append(f"REFERENCE CITATIONS: {', '.join(expected_citations)}")

    parts += ["", f"GENERATED ANSWER: {answer}"]
    return "\n".join(parts)


def _chat_model_for(provider: JudgeProvider):
    if provider == JudgeProvider.MERCURY:
        return get_mercury_judge_model()
    return get_ollama_judge_model()


def evaluate_answer(
    query: str,
    documents: list[Document],
    graph_context: list[str],
    answer: str,
    reference: tuple[str, list[str]] | None = None,
    provider: JudgeProvider | None = None,
) -> JudgeScores:
    """4.1/4.2: judges one generated answer against its own retrieved
    context (+ graph facts), returning four 0-1 scores and rationale.
    `provider` defaults to `Settings.judge_provider` (today always
    MERCURY for every call site) -- the parameter exists so a future
    per-domain override is a one-line change at the call site, not a
    rewrite here. Raises `JudgeUnavailableError` on any provider
    failure -- the caller (evaluation/service.py::evaluate_query_log,
    Phase 3) is responsible for turning that into a terminal `FAILED`
    status rather than leaving an `EvaluationResult` row at `PENDING`.
    """
    if provider is None:
        provider = JudgeProvider(get_settings().judge_provider)

    system_prompt = _JUDGE_SYSTEM_PROMPT_WITH_REFERENCE if reference else _JUDGE_SYSTEM_PROMPT
    user_prompt = build_judge_prompt(query, documents, graph_context, answer, reference)

    chat_model = _chat_model_for(provider)
    structured_model = chat_model.with_structured_output(JudgeScores, method="json_schema")
    try:
        return structured_model.invoke([("system", system_prompt), ("human", user_prompt)])
    except Exception as e:
        logging.warning(f"Judge evaluation failed via {provider.value} provider: {e}")
        raise JudgeUnavailableError(f"Judge evaluation via the '{provider.value}' provider failed") from e
