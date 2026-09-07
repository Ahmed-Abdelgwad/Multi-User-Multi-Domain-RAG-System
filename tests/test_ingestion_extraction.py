from src.ingestion import extraction
from src.entities.enums import DocumentSourceType
from tests.fixtures_documents import (
    make_pdf_bytes,
    make_pdf_with_malformed_creation_date_bytes,
    make_pdf_with_paragraphs_bytes,
    make_pdf_with_table_bytes,
    make_docx_bytes,
    make_docx_with_table_bytes,
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


def test_reconstruct_paragraphs_joins_wrapped_lines_and_splits_on_terminal_punctuation():
    # PyPDFLoader's actual output shape (verified live): one line per
    # rendered line, no blank lines between paragraphs at all.
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
    # verification: PyPDFLoader emits no blank lines between paragraphs
    # (unlike Docx2txtLoader, confirmed separately), so a real
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
    assert "[TABLE from page" in result.text
    assert "Alice" in result.text


def test_extract_pdf_camelot_failure_does_not_fail_whole_document(monkeypatch):
    def _boom(pdf_path):
        raise RuntimeError("ghostscript not found")
    monkeypatch.setattr(extraction, "_extract_tables_camelot", _boom)

    # Should not raise -- table extraction is a bonus on top of the
    # must-succeed text path, not a dependency of it.
    result = extraction.extract_pdf(make_pdf_bytes("Hello from a real PDF"))

    assert "Hello from a real PDF" in result.text
    assert result.tables == []


def test_extract_docx_with_real_table_via_python_docx():
    result = extraction.extract_docx(make_docx_with_table_bytes())

    assert len(result.tables) == 1
    table = result.tables[0]
    assert "Alice" in table.markdown
    assert "Domain Admin" in table.markdown
    assert "[TABLE from page" in result.text


def test_extract_docx_without_table_has_no_tables():
    result = extraction.extract_docx(make_docx_bytes("Hello from a real DOCX"))

    assert result.tables == []
