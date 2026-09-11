from src.retrieval import ner


class _FakeSpan:
    def __init__(self, text, label, n_tokens):
        self.text = text
        self.label_ = label
        self._n = n_tokens

    def __len__(self):
        return self._n


class _FakeDoc:
    def __init__(self, n_tokens, ents):
        self._n = n_tokens
        self.ents = ents

    def __len__(self):
        return self._n


def _fake_model(n_tokens, ents):
    # analyze_query calls get_ner_model()(query) -- return a callable
    # that ignores the query and yields a canned doc.
    return lambda _query: _FakeDoc(n_tokens, ents)


def test_analyze_query_returns_entity_text_label_pairs(monkeypatch):
    monkeypatch.setattr(ner, "get_ner_model", lambda: _fake_model(
        9, [_FakeSpan("Alice Johnson", "PER", 2), _FakeSpan("Acme Corporation", "ORG", 2)]
    ))

    entities, ratio = ner.analyze_query("Where does Alice Johnson work at Acme Corporation")

    assert entities == [("Alice Johnson", "PER"), ("Acme Corporation", "ORG")]
    assert ratio == 4 / 9


def test_analyze_query_no_entities_gives_zero_ratio(monkeypatch):
    monkeypatch.setattr(ner, "get_ner_model", lambda: _fake_model(6, []))

    entities, ratio = ner.analyze_query("what is the meaning of all this")

    assert entities == []
    assert ratio == 0.0


def test_analyze_query_empty_query_does_not_divide_by_zero(monkeypatch):
    monkeypatch.setattr(ner, "get_ner_model", lambda: _fake_model(0, []))

    entities, ratio = ner.analyze_query("")

    assert entities == []
    assert ratio == 0.0


def test_analyze_query_all_tokens_are_entities_gives_ratio_one(monkeypatch):
    monkeypatch.setattr(ner, "get_ner_model", lambda: _fake_model(
        2, [_FakeSpan("Berlin", "LOC", 1), _FakeSpan("Paris", "LOC", 1)]
    ))

    _entities, ratio = ner.analyze_query("Berlin Paris")

    assert ratio == 1.0
