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


MIN_NATIVE_TEXT_CHARS = 20
MIN_TABLE_ACCURACY = 50


@dataclass(frozen=True)
class TableExtract:
    
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

    
    text = _reconstruct_paragraphs(text)

    if tables:
        
        text = text + _tables_to_appendix(tables)

    return ExtractionResult(
        text=text, ocr_used=ocr_used, author=author, doc_created_at=doc_created_at, tables=tables
    )


def _ocr_pdf(raw_bytes: bytes) -> str:
    
    from pdf2image import convert_from_bytes
    import pytesseract

    images = convert_from_bytes(raw_bytes)
    return "\n".join(pytesseract.image_to_string(image) for image in images)


def _extract_tables_camelot(pdf_path: str) -> list[TableExtract]:
    
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
