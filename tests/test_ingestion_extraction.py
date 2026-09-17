from src.ingestion import extraction
from src.entities.enums import DocumentSourceType
from tests.fixtures_documents import (
    make_pdf_bytes,
    make_pdf_with_malformed_creation_date_bytes,
    make_pdf_with_paragraphs_bytes,
    make_pdf_with_table_bytes,
    make_pdf_with_text_around_table_bytes,
    make_docx_bytes,
    make_docx_with_table_bytes,
    make_docx_with_text_around_table_bytes,
)


def test_extract_pdf_returns_native_text_without_ocr():
    result = extraction.extract_pdf(make_pdf_bytes("Hello from a real PDF"))

    assert "Hello from a real PDF" in result.text
    assert result.ocr_used is False


def test_extract_pdf_survives_malformed_creation_date():
    # Regression test for a real bug found live against a real resume
    # PDF (not any prior fixture): a malformed `/CreationDate` string
    # crashed `PdfReader(...).metadata.creation_date` and took the whole
    # document to `failed`, even though the text itself extracted fine.
    result = extraction.extract_pdf(make_pdf_with_malformed_creation_date_bytes("Hello from a real PDF"))

    assert "Hello from a real PDF" in result.text
    assert result.doc_created_at is None


def test_strip_nul_bytes_removes_embedded_nul_characters():
    assert extraction._strip_nul_bytes("Hello\x00World") == "HelloWorld"
    assert extraction._strip_nul_bytes("clean text") == "clean text"


class _FakeGlyph:
    def __init__(self, text: str, bbox: tuple[float, float, float, float]):
        self.text = text
        self.bbox = bbox


class _FakeTextObj:
    """Mimics `playa`'s `TextObject`: iterable over per-glyph objects,
    with its own bbox derived from its glyphs (for page-level sorting)."""

    def __init__(self, glyphs: list[_FakeGlyph]):
        self.object_type = "text"
        self._glyphs = glyphs
        xs = [g.bbox[0] for g in glyphs] + [g.bbox[2] for g in glyphs]
        ys = [g.bbox[1] for g in glyphs] + [g.bbox[3] for g in glyphs]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))

    def __iter__(self):
        return iter(self._glyphs)


def test_text_object_chars_inserts_spaces_at_word_boundaries():
    # Regression for a real bug found live against a real arXiv-generated
    # PDF: `playa`'s raw `.chars` property concatenates decoded glyphs with
    # no inter-word spacing at all when a PDF encodes spacing between words
    # purely via `TJ`-array position adjustments rather than a literal space
    # glyph -- a whole line decoded to one glued-together run of words
    # ("FromLocaltoGlobal..."). Real measurements on that document: genuine
    # word gaps were 27-35% of glyph height; kerning noise within a word
    # never exceeded ~6%. This fixture reproduces that exact shape.
    glyphs = [
        _FakeGlyph("H", (0.0, 0.0, 8.0, 10.0)),
        _FakeGlyph("i", (8.0, 0.0, 10.0, 10.0)),  # no gap: same word
        _FakeGlyph("t", (13.0, 0.0, 15.0, 10.0)),  # gap 3.0 / height 10 = 30%: new word
        _FakeGlyph("h", (15.0, 0.0, 17.0, 10.0)),
        _FakeGlyph("e", (17.0, 0.0, 19.0, 10.0)),
        _FakeGlyph("r", (19.2, 0.0, 21.0, 10.0)),  # 2% kerning gap: same word
        _FakeGlyph("e", (21.0, 0.0, 23.0, 10.0)),
    ]

    assert extraction._text_object_chars(_FakeTextObj(glyphs)) == "Hi there"


def test_text_object_chars_does_not_double_space_a_real_space_glyph():
    glyphs = [
        _FakeGlyph("a", (0.0, 0.0, 8.0, 10.0)),
        _FakeGlyph(" ", (8.0, 0.0, 12.0, 10.0)),
        _FakeGlyph("b", (12.0, 0.0, 20.0, 10.0)),
    ]

    assert extraction._text_object_chars(_FakeTextObj(glyphs)) == "a b"


def test_page_plain_text_strips_nul_bytes():
    # Regression for a real bug found live: uploading a real arXiv-generated
    # PDF failed the whole document with a genuine Postgres error ("A string
    # literal cannot contain NUL (0x00) characters") -- playa's character-level
    # decoding of that PDF's embedded/CID-keyed fonts decoded certain glyphs
    # to a literal NUL byte, which Postgres text columns reject outright.
    page = [_FakeTextObj([_FakeGlyph("Hello\x00World", (0.0, 0.0, 10.0, 10.0))])]

    assert extraction._page_plain_text(page) == "HelloWorld"


def test_reconstruct_paragraphs_joins_wrapped_lines_and_splits_on_terminal_punctuation():
    # playa's actual output shape (verified live, same as PyPDFLoader's
    # before it): one line per rendered line, no blank lines between
    # paragraphs at all.
    text = "This is a wrapped\nparagraph that spans two lines.\nThis is a second paragraph."

    result = extraction._reconstruct_paragraphs(text)

    assert result == (
        "This is a wrapped paragraph that spans two lines.\n\n"
        "This is a second paragraph."
    )


def test_reconstruct_paragraphs_preserves_existing_blank_lines():
    text = "First paragraph.\n\nSecond paragraph."

    assert extraction._reconstruct_paragraphs(text) == text


def test_extract_pdf_real_multi_paragraph_pdf_recovers_paragraph_boundaries():
    # Regression test for a real bug found during live docker-compose
    # verification: the PDF text layer emits no blank lines between
    # paragraphs (unlike Docx2txtLoader, confirmed separately), so a real
    # multi-paragraph PDF's whole body was being treated as a single
    # paragraph by chunking/chunker.py's blank-line split -- silently
    # defeating Paragraph Group Chunking for every PDF.
    paragraphs = [
        "This is the first paragraph of a real multi-paragraph PDF document.",
        "This is the second paragraph, distinct from the first one.",
        "This is the third and final paragraph in this test document.",
    ]

    result = extraction.extract_pdf(make_pdf_with_paragraphs_bytes(paragraphs))

    recovered = [p for p in result.text.split("\n\n") if p.strip()]
    assert recovered == paragraphs
    assert len(result.elements) == 1
    assert result.elements[0].kind == "text"


def test_extract_docx_returns_text_and_author():
    result = extraction.extract_docx(make_docx_bytes("Hello from a real DOCX", author="Jane Doe"))

    assert "Hello from a real DOCX" in result.text
    assert result.author == "Jane Doe"
    assert result.ocr_used is False


def test_extract_dispatches_by_source_type(monkeypatch):
    calls = []
    monkeypatch.setattr(extraction, "extract_pdf", lambda raw: calls.append("pdf") or "pdf-result")
    monkeypatch.setattr(extraction, "extract_docx", lambda raw: calls.append("docx") or "docx-result")

    assert extraction.extract(DocumentSourceType.PDF, b"x") == "pdf-result"
    assert extraction.extract(DocumentSourceType.DOCX, b"x") == "docx-result"
    assert calls == ["pdf", "docx"]


def test_extract_unsupported_source_type_raises():
    try:
        extraction.extract(DocumentSourceType.CSV, b"a,b\n1,2")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_extract_pdf_triggers_ocr_fallback_when_native_text_is_sparse(monkeypatch):
    # A blank PDF has ~0 extractable native text, so this should hit the
    # OCR path. The OCR call itself is mocked here since the
    # tesseract-ocr/poppler-utils system binaries it shells out to live
    # in the Docker image (see Dockerfile), not necessarily on whatever
    # machine runs `pytest` directly -- the real OCR path is proven by
    # the live docker-compose smoke test instead.
    monkeypatch.setattr(extraction, "_ocr_pdf", lambda raw: "OCR TEXT")

    result = extraction.extract_pdf(make_pdf_bytes(text=None))

    assert result.ocr_used is True
    assert result.text == "OCR TEXT"
    assert result.elements == [extraction.DocumentElement(kind="text", content="OCR TEXT")]


def test_extract_pdf_scanned_path_never_calls_camelot(monkeypatch):
    """Camelot can't find anything on a page with no text/line layer, so
    the scanned/OCR path must skip it entirely rather than call it and
    get nothing (or an error) back.
    """
    def _boom(pdf_path):
        raise AssertionError("Camelot should not be called on the OCR/scanned path")
    monkeypatch.setattr(extraction, "_extract_tables_camelot", _boom)
    monkeypatch.setattr(extraction, "_ocr_pdf", lambda raw: "OCR TEXT")

    result = extraction.extract_pdf(make_pdf_bytes(text=None))

    assert result.tables == []


def test_extract_pdf_with_real_table_via_camelot():
    # Real Camelot call (ghostscript is available on this machine, see
    # earlier verification) against a real bordered PDF table -- proves
    # the lattice flavor + markdown rendering end to end, not just the
    # dispatch logic around it.
    result = extraction.extract_pdf(make_pdf_with_table_bytes())

    assert len(result.tables) == 1
    table = result.tables[0]
    assert "Alice" in table.markdown
    assert "Domain Admin" in table.markdown
    # The old markdown appendix is gone -- elements is chunking's single
    # source of truth for tables now, not a second copy glued onto `text`.
    # `text` is still a full raw page dump (unchanged from before), so a
    # table's cell text naturally still appears in it once, same as any
    # other on-page text pypdf/playa would read.
    assert "[TABLE from page" not in result.text


def test_extract_pdf_preserves_text_around_table_in_true_order():
    # Regression test for the real ordering problem: a table used to
    # always land after *all* prose regardless of where it actually
    # appeared. This document has prose both before and after the same
    # table on one page. Verified separately against two real,
    # user-supplied PDFs (a CV and a 9-page, 31-table spec document) --
    # every table landed correctly between its own surrounding sections.
    result = extraction.extract_pdf(make_pdf_with_text_around_table_bytes(
        before_text="Text before the table.", after_text="Text after the table.",
    ))

    kinds = [e.kind for e in result.elements]
    assert kinds == ["text", "table", "text"]
    assert "Text before the table." in result.elements[0].content
    assert "Bob" in result.elements[1].content
    assert "Text after the table." in result.elements[2].content


def test_extract_pdf_camelot_failure_does_not_fail_whole_document(monkeypatch):
    def _boom(pdf_path):
        raise RuntimeError("ghostscript not found")
    monkeypatch.setattr(extraction, "_extract_tables_camelot", _boom)

    # Should not raise -- table extraction is a bonus on top of the
    # must-succeed text path, not a dependency of it.
    result = extraction.extract_pdf(make_pdf_bytes("Hello from a real PDF"))

    assert "Hello from a real PDF" in result.text
    assert result.tables == []
    assert len(result.elements) == 1
    assert result.elements[0].kind == "text"


def test_extract_docx_with_real_table_via_python_docx():
    result = extraction.extract_docx(make_docx_with_table_bytes())

    assert len(result.tables) == 1
    table = result.tables[0]
    assert "Alice" in table.markdown
    assert "Domain Admin" in table.markdown


def test_extract_docx_preserves_text_around_table_in_true_order():
    # Regression test matching the PDF case above -- DOCX's XML supports
    # true document-order interleaving natively (see `_docx_elements`).
    result = extraction.extract_docx(make_docx_with_text_around_table_bytes(
        before_text="Text before the table.", after_text="Text after the table.",
    ))

    kinds = [e.kind for e in result.elements]
    assert kinds == ["text", "table", "text"]
    assert "Text before the table." in result.elements[0].content
    assert "Bob" in result.elements[1].content
    assert "Text after the table." in result.elements[2].content


def test_extract_docx_without_table_has_no_tables():
    result = extraction.extract_docx(make_docx_bytes("Hello from a real DOCX"))

    assert result.tables == []
    assert len(result.elements) == 1
    assert result.elements[0].kind == "text"


def test_is_figure_data_paragraph_detects_bare_chart_labels():
    # Regression for a real bug found live: a vector-drawn chart (not a
    # raster image, so real extractable text) decoded as a flat run of
    # axis/legend numbers with no link back to which config/metric each
    # belonged to -- confirmed against a real paper's Figure 4.
    chart_soup = "0 20 40 60 80 100 120 Rate (%) 100% 50% 0% 98% 50% 0%"

    assert extraction._is_figure_data_paragraph(chart_soup) is True


def test_is_figure_data_paragraph_excludes_bibliography_entries_with_urls():
    # Regression for a real false positive found live: a reference-list
    # entry's arXiv id/DOI/page range can score a *higher* digit ratio
    # than a genuine chart paragraph (e.g. "arXiv preprint
    # arXiv:2404.07220 1, 1 (2024), 1-12." scored 0.71). Every such case
    # found in the real document carried a URL/doi:/arxiv: marker no
    # genuine chart axis/legend text ever has.
    citation = (
        "[8] Alex Garcia. 2024. sqlite-vec: A vector search SQLite "
        "extension. GitHub repository. https://github.com/asg017/sqlite-vec "
        "Accessed: 2026-04-25."
    )

    assert extraction._is_figure_data_paragraph(citation) is False


def test_is_figure_data_paragraph_excludes_leading_reference_number_without_url():
    # A reference entry can wrap such that its own URL lands in the next
    # paragraph, leaving no http/doi/arxiv marker in this fragment --
    # the leading "[N]" citation number is the fallback signal.
    citation_fragment = "[28] OpenAI. 2025. gpt-oss-120b & gpt-oss-20b Model Card."

    assert extraction._is_figure_data_paragraph(citation_fragment) is False


def test_is_figure_data_paragraph_does_not_flag_ordinary_prose():
    prose_with_numbers = (
        "This is negligible relative to inference time (about 3-7s for "
        "API-based, about 450ms for self-hosted GPU)."
    )

    assert extraction._is_figure_data_paragraph(prose_with_numbers) is False


def test_is_figure_data_paragraph_requires_a_minimum_token_count():
    assert extraction._is_figure_data_paragraph("100% 0%") is False


def test_is_figure_caption_matches_figure_heading():
    assert extraction._is_figure_caption("Figure 4: Empirical evaluation results.") is True
    assert extraction._is_figure_caption("This mentions Figure 4 in passing.") is False


def test_split_figure_blocks_groups_chart_data_with_its_caption():
    text = (
        "Normal prose paragraph before the chart.\n\n"
        "0 20 40 60 80 100 120 Rate (%) 100% 50% 0% 98% 50% 0%\n\n"
        "Figure 4: Empirical evaluation results across five dimensions.\n\n"
        "Normal prose paragraph after the chart."
    )

    elements = extraction._split_figure_blocks(text)

    kinds = [e.kind for e in elements]
    assert kinds == ["text", "figure", "text"]
    assert "before the chart" in elements[0].content
    assert "98%" in elements[1].content
    assert "Figure 4:" in elements[1].content
    assert "after the chart" in elements[2].content


def test_split_figure_blocks_with_no_figure_data_returns_one_text_element():
    text = "First paragraph.\n\nSecond paragraph."

    elements = extraction._split_figure_blocks(text)

    assert len(elements) == 1
    assert elements[0].kind == "text"


def test_extract_pdf_tags_chart_like_content_as_figure():
    paragraphs = [
        "This section discusses the evaluation methodology in detail.",
        "0 20 40 60 80 100 120 Rate (%) 100% 50% 0% 98% 50% 0%",
        "Figure 4: Empirical evaluation results across five dimensions.",
        "The next section discusses related work in the field.",
    ]

    result = extraction.extract_pdf(make_pdf_with_paragraphs_bytes(paragraphs))

    kinds = [e.kind for e in result.elements]
    assert "figure" in kinds
    figure_element = next(e for e in result.elements if e.kind == "figure")
    assert "98%" in figure_element.content
    assert "Figure 4:" in figure_element.content
