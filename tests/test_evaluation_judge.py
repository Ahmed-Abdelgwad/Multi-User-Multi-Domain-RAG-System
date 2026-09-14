import pytest
from langchain_core.documents import Document
from src.entities.enums import JudgeProvider
from src.exceptions import JudgeUnavailableError
from src.evaluation import judge


class _FakeStructuredModel:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return self.result


class _FakeChatModel:
    def __init__(self, result=None, error=None):
        self.structured = _FakeStructuredModel(result=result, error=error)
        self.with_structured_output_calls = []

    def with_structured_output(self, schema, method=None):
        self.with_structured_output_calls.append((schema, method))
        return self.structured


_SCORES = judge.JudgeScores(
    faithfulness=1.0, faithfulness_rationale="all supported",
    relevance=1.0, relevance_rationale="on topic",
    completeness=1.0, completeness_rationale="covers it",
    citation_accuracy=1.0, citation_accuracy_rationale="citations check out",
)

_DOCS = [Document(page_content="Alice Johnson works at Acme Corporation.", metadata={"chunk_id": "c1"})]


# --- build_judge_prompt ---

def test_build_judge_prompt_includes_context_graph_and_answer():
    prompt = judge.build_judge_prompt(
        "Where does Alice work?", _DOCS, ["person:Alice Johnson --works_at--> organization:Acme Corporation"],
        "Alice works at Acme [1].",
    )
    assert "QUERY: Where does Alice work?" in prompt
    assert "[1] Alice Johnson works at Acme Corporation." in prompt
    assert "GRAPH FACTS:" in prompt
    assert "person:Alice Johnson --works_at--> organization:Acme Corporation" in prompt
    assert "GENERATED ANSWER: Alice works at Acme [1]." in prompt
    assert "REFERENCE" not in prompt


def test_build_judge_prompt_omits_graph_section_when_no_entities():
    prompt = judge.build_judge_prompt("q", _DOCS, [], "a")
    assert "GRAPH FACTS" not in prompt


def test_build_judge_prompt_includes_reference_when_provided():
    prompt = judge.build_judge_prompt(
        "q", _DOCS, [], "a", reference=("The reference answer.", ["c1", "c2"]),
    )
    assert "REFERENCE ANSWER: The reference answer." in prompt
    assert "REFERENCE CITATIONS: c1, c2" in prompt


# --- evaluate_answer ---

def test_evaluate_answer_defaults_to_mercury_provider(monkeypatch):
    monkeypatch.setattr(judge, "get_settings", lambda: type("S", (), {"judge_provider": "mercury"})())
    fake_model = _FakeChatModel(result=_SCORES)
    monkeypatch.setattr(judge, "get_mercury_judge_model", lambda: fake_model)

    def _boom():
        raise AssertionError("get_ollama_judge_model should not be called when provider is mercury")
    monkeypatch.setattr(judge, "get_ollama_judge_model", _boom)

    result = judge.evaluate_answer("q", _DOCS, [], "a")

    assert result == _SCORES
    assert fake_model.with_structured_output_calls[0][0] is judge.JudgeScores
    assert fake_model.with_structured_output_calls[0][1] == "json_schema"


def test_evaluate_answer_uses_explicit_provider_override(monkeypatch):
    fake_model = _FakeChatModel(result=_SCORES)
    monkeypatch.setattr(judge, "get_ollama_judge_model", lambda: fake_model)

    def _boom():
        raise AssertionError("get_mercury_judge_model should not be called with an explicit OLLAMA override")
    monkeypatch.setattr(judge, "get_mercury_judge_model", _boom)

    result = judge.evaluate_answer("q", _DOCS, [], "a", provider=JudgeProvider.OLLAMA)
    assert result == _SCORES


def test_evaluate_answer_includes_reference_in_prompt_sent_to_model(monkeypatch):
    fake_model = _FakeChatModel(result=_SCORES)
    monkeypatch.setattr(judge, "get_mercury_judge_model", lambda: fake_model)

    judge.evaluate_answer("q", _DOCS, [], "a", reference=("expected answer text", []), provider=JudgeProvider.MERCURY)

    sent_messages = fake_model.structured.calls[0]
    system_msg, human_msg = sent_messages[0][1], sent_messages[1][1]
    assert "REFERENCE ANSWER" in system_msg  # stricter system prompt swapped in
    assert "expected answer text" in human_msg


def test_evaluate_answer_wraps_provider_failure(monkeypatch):
    fake_model = _FakeChatModel(error=RuntimeError("network down"))
    monkeypatch.setattr(judge, "get_mercury_judge_model", lambda: fake_model)

    with pytest.raises(JudgeUnavailableError):
        judge.evaluate_answer("q", _DOCS, [], "a", provider=JudgeProvider.MERCURY)
