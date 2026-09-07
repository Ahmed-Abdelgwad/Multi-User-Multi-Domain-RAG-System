"""Pure text/metadata extraction for ingested documents (spec 2.1), built
on LangChain's document loaders (PyPDFLoader / Docx2txtLoader) -- kept
from the stack carried over from the discarded prior attempt at this
project (`langchain-community`), rather than reaching for pypdf/python-docx
directly. No DB or Celery import here -- kept separate from `service.py`
so extraction itself is unit-testable without a database or broker.

LangChain's loaders only take a file path (no in-memory bytes), so raw
bytes (downloaded from MinIO) are spooled to a temp file first. Neither
loader surfaces document-level metadata (author/creation date) -- that
part still reads the underlying pypdf/python-docx metadata objects
directly, since spec 2.1 explicitly requires author/creation-date capture
at ingest time.

Table extraction is folded in here too, since plain text extraction
flattens a table's rows/columns into unstructured running text that no
downstream chunking strategy can recover: PDFs use Camelot (reads the
PDF's own text/line objects -- only works on text-native pages, so it's
skipped entirely for the OCR/scanned-PDF path, which has none); DOCX uses
python-docx's own `document.tables` (its XML already models tables
structurally, no separate library needed).
"""
import logging
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from pypdf import PdfReader
import docx as python_docx
from docx.document import Document as DocxDocument
from src.entities.enums import DocumentSourceType

# Below this many extracted characters, native text extraction is treated
# as having failed (e.g. a scanned/image-only PDF) and the OCR fallback
# (spec 2.1: "OCR fallback for scanned PDFs") kicks in instead.
MIN_NATIVE_TEXT_CHARS = 20

# Camelot's own per-table accuracy score (0-100); below this a "table" is
# more likely noise (e.g. a body-text paragraph misread as a 1-column
# table by the `stream` flavor) than a real table.
MIN_TABLE_ACCURACY = 50


@dataclass(frozen=True)
class TableExtract:
    # For PDFs this is the real source page number (1-based, from
    # Camelot). DOCX has no page concept at the XML level without full
    # layout rendering, so `extract_docx` uses the table's sequential
    # position in the document instead -- still a stable, meaningful
    # identifier, just not a literal page.
    page: int
    markdown: str


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    ocr_used: bool
    author: str | None
    doc_created_at: datetime | None
    tables: list[TableExtract] = field(default_factory=list)


def extract(source_type: DocumentSourceType, raw_bytes: bytes) -> ExtractionResult:
    if source_type == DocumentSourceType.PDF:
        return extract_pdf(raw_bytes)
    if source_type == DocumentSourceType.DOCX:
        return extract_docx(raw_bytes)
    raise ValueError(f"Text extraction not implemented for source_type={source_type}")


def _spool_to_tempfile(raw_bytes: bytes, suffix: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(raw_bytes)
    finally:
        tmp.close()
    return Path(tmp.name)


def _tables_to_appendix(tables: list[TableExtract]) -> str:
    return "\n\n" + "\n\n".join(f"[TABLE from page {t.page}]\n{t.markdown}" for t in tables)


def _read_pdf_metadata(tmp_path: Path) -> tuple[str | None, datetime | None]:
    """Reads author/creation-date off pypdf's own metadata object. Found
    live (not by any fixture) on a real PDF: `meta.creation_date` parses
    the PDF's raw `/CreationDate` string internally and raises on a
    malformed one (e.g. a trailing `'` with no UTC-offset minutes, as in
    `D:20260415123806Z'`) -- pypdf doesn't tolerate every date variant
    real-world PDF producers emit. Metadata is a bonus on top of the
    must-succeed text extraction path (same treatment as table
    extraction below), so any failure here is caught and logged rather
    than failing the whole document.
    """
    try:
        meta = PdfReader(str(tmp_path)).metadata
    except Exception as e:
        logging.warning(f"PDF metadata read failed for {tmp_path}: {e}")
        return None, None
    if not meta:
        return None, None

    author = meta.author
    try:
        doc_created_at = meta.creation_date
    except Exception as e:
        logging.warning(f"PDF creation_date parse failed for {tmp_path}: {e}")
        doc_created_at = None
    return author, doc_created_at


def _reconstruct_paragraphs(text: str) -> str:
    """Approximates paragraph boundaries in line-based PDF/OCR text: lines
    not ending in terminal punctuation are wrapped continuations of the
    same paragraph (joined with a space); a line ending in `.`/`!`/`?`/`:`
    ends it (a blank line is inserted). Not perfect -- a multi-sentence
    paragraph becomes several reconstructed "paragraphs" -- but that
    degrades to sentence-level grouping, which the literature review
    behind PGC's design found performs comparably to true paragraph-level
    grouping (see the plan's SIGIR cross-check), a much better fallback
    than the single giant blob a naive `\n`-preserving join produces.
    """
    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(stripped)
        if stripped[-1] in ".!?:":
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def extract_pdf(raw_bytes: bytes) -> ExtractionResult:
    tmp_path = _spool_to_tempfile(raw_bytes, ".pdf")
    try:
        text = "\n".join(page.page_content for page in PyPDFLoader(str(tmp_path)).load())

        # PyPDFLoader's per-page metadata is just {source, page}; the
        # document-level fields (author/creation date) come from pypdf's
        # own metadata object instead.
        author, doc_created_at = _read_pdf_metadata(tmp_path)

        ocr_used = len(text.strip()) < MIN_NATIVE_TEXT_CHARS
        if ocr_used:
            # Scanned/image-only page: there's no text/line layer for
            # Camelot to read (it would find nothing, or error), so skip
            # it entirely and go straight to OCR rather than wasting a
            # call on a page it can't help with.
            tables: list[TableExtract] = []
        else:
            try:
                tables = _extract_tables_camelot(str(tmp_path))
            except Exception as e:
                # Belt-and-braces on top of the per-flavor try/except
                # inside _extract_tables_camelot: table extraction must
                # never fail the whole document, since text extraction
                # (below) is the must-succeed path.
                logging.warning(f"Table extraction failed for {tmp_path}: {e}")
                tables = []
    finally:
        tmp_path.unlink(missing_ok=True)

    if ocr_used:
        text = _ocr_pdf(raw_bytes)

    # PyPDFLoader (and pytesseract's OCR output) has one line per rendered
    # line on the page -- PDFs carry no real paragraph markup the way
    # DOCX does (Docx2txtLoader correctly emits blank-line-separated
    # paragraphs; verified directly against real output). Without this,
    # `chunking/chunker.py`'s paragraph split (on blank lines) sees the
    # entire page as one giant "paragraph", silently defeating Paragraph
    # Group Chunking for every PDF. Reconstructing approximate paragraph
    # breaks here keeps that contract (text has real `\n\n` boundaries)
    # true for every source type, so the chunker itself stays a clean,
    # format-agnostic PGC implementation with no PDF-specific knowledge.
    text = _reconstruct_paragraphs(text)

    if tables:
        # Folded into extracted_text too (not just the structured `tables`
        # field) so table content is never lost even before anything
        # downstream is table-aware -- plain full-text search/chunking
        # still sees it. A mixed PDF (native text + tables) gets both the
        # PyPDFLoader text and the Camelot tables appended below it.
        text = text + _tables_to_appendix(tables)

    return ExtractionResult(
        text=text, ocr_used=ocr_used, author=author, doc_created_at=doc_created_at, tables=tables
    )


def _ocr_pdf(raw_bytes: bytes) -> str:
    # Imported lazily: these need the tesseract-ocr/poppler-utils system
    # packages (see Dockerfile) which aren't required at all for the
    # common case of text-native PDFs -- only paid for on the scanned-PDF
    # fallback path.
    from pdf2image import convert_from_bytes
    import pytesseract

    images = convert_from_bytes(raw_bytes)
    return "\n".join(pytesseract.image_to_string(image) for image in images)


def _extract_tables_camelot(pdf_path: str) -> list[TableExtract]:
    """Tries Camelot's `lattice` flavor (ruled/bordered tables) first, then
    falls back to `stream` (whitespace-aligned, borderless tables) only if
    lattice found nothing worth keeping. Any Camelot/ghostscript failure
    is caught here and logged rather than failing the whole document --
    table extraction is a bonus on top of the must-succeed text path, not
    a dependency of it.
    """
    import camelot

    for flavor in ("lattice", "stream"):
        try:
            found = camelot.read_pdf(pdf_path, flavor=flavor, pages="all")
        except Exception as e:
            logging.warning(f"Camelot flavor={flavor} failed for {pdf_path}: {e}")
            continue

        qualifying = [
            TableExtract(
                page=int(table.parsing_report.get("page", 0)),
                markdown=table.df.to_markdown(index=False),
            )
            for table in found
            if table.parsing_report.get("accuracy", 0) >= MIN_TABLE_ACCURACY
            and table.df.shape[0] >= 2
            and table.df.shape[1] >= 2
        ]
        if qualifying:
            return qualifying

    return []


def extract_docx(raw_bytes: bytes) -> ExtractionResult:
    tmp_path = _spool_to_tempfile(raw_bytes, ".docx")
    try:
        text = "\n".join(doc.page_content for doc in Docx2txtLoader(str(tmp_path)).load())

        document = python_docx.Document(str(tmp_path))

        # Docx2txtLoader doesn't surface core_properties; read those via
        # python-docx directly.
        props = document.core_properties
        author = props.author or None
        doc_created_at = props.created

        tables = _extract_tables_python_docx(document)
    finally:
        tmp_path.unlink(missing_ok=True)

    if tables:
        text = text + _tables_to_appendix(tables)

    return ExtractionResult(
        text=text, ocr_used=False, author=author, doc_created_at=doc_created_at, tables=tables
    )


def _extract_tables_python_docx(document: DocxDocument) -> list[TableExtract]:
    """DOCX's XML already models tables structurally (unlike PDF, where
    they have to be reconstructed from position), so this reads
    `document.tables` directly -- no Camelot involved, per the requirement
    that Camelot stays PDF-only.
    """
    tables: list[TableExtract] = []
    for index, table in enumerate(document.tables, start=1):
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if len(rows) < 2 or any(len(row) < 2 for row in rows):
            continue
        tables.append(TableExtract(page=index, markdown=_rows_to_markdown(rows)))
    return tables


def _rows_to_markdown(rows: list[list[str]]) -> str:
    header, *body = rows
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)
