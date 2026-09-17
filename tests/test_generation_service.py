import pytest
from langchain_core.documents import Document
from src.entities.enums import LLMRoute
from src.exceptions import GenerationUnavailableError
from src.generation import service


class _Config:
    def __init__(self, default=LLMRoute.API, keywords=None):
        self.llm_routing_default = default
        self.llm_routing_sensitive_keywords = keywords or []


class _Settings:
    def __init__(self, local_llm_enabled):
        self.local_llm_enabled = local_llm_enabled


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeChatModel:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return _FakeResponse(self.content)


# --- classify_llm_route ---

def test_classify_no_keyword_match_uses_domain_default():
    config = _Config(default=LLMRoute.API, keywords=["salary", "ssn"])
    assert service.classify_llm_route("what is Acme's headquarters?", config) == LLMRoute.API


def test_classify_keyword_match_forces_local_regardless_of_default():
    config = _Config(default=LLMRoute.API, keywords=["salary"])
    assert service.classify_llm_route("What is Alice's SALARY?", config) == LLMRoute.LOCAL


def test_classify_default_local_with_no_keywords_configured():
    config = _Config(default=LLMRoute.LOCAL, keywords=[])
    assert service.classify_llm_route("anything at all", config) == LLMRoute.LOCAL


# --- generate_answer ---

def test_generate_answer_local_disabled_returns_stub_without_invoking_model(monkeypatch):
    config = _Config(default=LLMRoute.LOCAL)
    monkeypatch.setattr(service, "get_settings", lambda: _Settings(local_llm_enabled=False))

    def _boom():
        raise AssertionError("get_local_chat_model should not be called when disabled")

    monkeypatch.setattr(service.llm, "get_local_chat_model", _boom)

    answer, route = service.generate_answer("q", [], config)
    assert answer == service.LOCAL_UNAVAILABLE_MESSAGE
    assert route == LLMRoute.LOCAL


def test_generate_answer_api_route_invokes_chat_model_with_context(monkeypatch):
    config = _Config(default=LLMRoute.API)
    fake_model = _FakeChatModel(content="Acme is in Berlin [1].")
    monkeypatch.setattr(service.llm, "get_api_chat_model", lambda: fake_model)

    docs = [Document(page_content="Acme is headquartered in Berlin.", metadata={"chunk_id": "c1"})]
    answer, route = service.generate_answer("Where is Acme?", docs, config)

    assert answer == "Acme is in Berlin [1]."
    assert route == LLMRoute.API
    system_msg = fake_model.calls[0][0][1]
    assert "[1] Acme is headquartered in Berlin." in system_msg


def test_generate_answer_prompt_instructs_against_restating_the_answer(monkeypatch):
    # Regression for a real bug found live: the API-route model
    # (ibm-granite/granite-4.2-8b) sometimes restated its own already-
    # complete, correct answer 2-3 times in slightly different phrasing
    # within one completion instead of stopping cleanly -- confirmed
    # unrelated to hidden reasoning tokens (already disabled separately).
    config = _Config(default=LLMRoute.API)
    fake_model = _FakeChatModel(content="answer")
    monkeypatch.setattr(service.llm, "get_api_chat_model", lambda: fake_model)

    service.generate_answer("q", [], config)

    system_msg = fake_model.calls[0][0][1]
    assert "do not restate, repeat, or re-summarize" in system_msg


def test_generate_answer_local_route_when_enabled_invokes_local_model(monkeypatch):
    config = _Config(default=LLMRoute.LOCAL)
    monkeypatch.setattr(service, "get_settings", lambda: _Settings(local_llm_enabled=True))
    fake_model = _FakeChatModel(content="local answer")
    monkeypatch.setattr(service.llm, "get_local_chat_model", lambda: fake_model)

    answer, route = service.generate_answer("q", [], config)
    assert answer == "local answer"
    assert route == LLMRoute.LOCAL


def test_generate_answer_wraps_provider_failure(monkeypatch):
    config = _Config(default=LLMRoute.API)
    monkeypatch.setattr(service.llm, "get_api_chat_model", lambda: _FakeChatModel(error=RuntimeError("network down")))

    with pytest.raises(GenerationUnavailableError):
        service.generate_answer("q", [], config)
