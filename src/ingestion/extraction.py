import logging
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from langchain_community.document_loaders import Docx2txtLoader
from pypdf import PdfReader
import docx as python_docx
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from src.entities.enums import DocumentSourceType


MIN_NATIVE_TEXT_CHARS = 20
MIN_TABLE_ACCURACY = 50


@dataclass(frozen=True)
class TableExtract:
    page: int
    markdown: str
    bbox: tuple[float, float, float, float] | None = None  # native (bottom-up) PDF coords; None for DOCX


@dataclass(frozen=True)
class DocumentElement:
    
    kind: str
    content: str


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    ocr_used: bool
    author: str | None
    doc_created_at: datetime | None
    tables: list[TableExtract] = field(default_factory=list)
    elements: list[DocumentElement] = field(default_factory=list)


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


def _read_pdf_metadata(tmp_path: Path) -> tuple[str | None, datetime | None]:
    
    try:
        meta = PdfReader(str(tmp_path)).metadata
    except Exception as e:
        logging.warning(f"PDF metadata read failed for {tmp_path}: {e}")
        return None, None
    if not meta:
        return None, None

    author = _strip_nul_bytes(meta.author) if meta.author else None
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


def _strip_nul_bytes(text: str) -> str:
    # Certain embedded/CID-keyed fonts (seen live on a real arXiv-generated
    # PDF) decode undefined glyphs to a literal NUL (\x00) via playa/Camelot
    # -- Postgres text columns reject any string containing one outright,
    # failing the whole document. Strip at every point raw text first enters
    # this module, before it's wrapped in a dataclass or persisted.
    return text.replace("\x00", "")


_WORD_GAP_RATIO = 0.15


def _text_object_chars(text_obj) -> str:
    # `playa`'s own `.chars` property just concatenates a text object's
    # decoded glyphs with no inter-word spacing at all when a PDF encodes
    # spacing between words purely as a `TJ`-array position adjustment
    # rather than a literal space glyph -- confirmed live against a real
    # arXiv-generated PDF, where entire lines decoded to one unbroken run
    # of glued-together words (e.g. "FromLocaltoGlobal..."). Reconstruct
    # spacing from actual glyph positions: a genuine word gap on this
    # document measured 27-35% of the preceding glyph's height, while
    # kerning noise within a word never exceeded ~6%.
    parts: list[str] = []
    prev_bbox: tuple[float, float, float, float] | None = None
    for glyph in text_obj:
        text = glyph.text
        if text is None:
            continue
        bbox = glyph.bbox
        if prev_bbox is not None and not text.isspace():
            height = prev_bbox[3] - prev_bbox[1]
            gap = bbox[0] - prev_bbox[2]
            if height > 0 and gap / height > _WORD_GAP_RATIO:
                parts.append(" ")
        parts.append(text)
        prev_bbox = bbox
    return "".join(parts)


def _midpoint_y(obj) -> float:
    return (obj.bbox[1] + obj.bbox[3]) / 2


def _page_text_objects(page) -> list:
    """All of a page's text runs, in true top-to-bottom/left-to-right
    reading order -- confirmed live that `playa`'s bbox is top-down
    (smaller y = higher on the page) and one object per rendered line.
    """
    return sorted(
        (obj for obj in page if obj.object_type == "text"),
        key=lambda o: (_midpoint_y(o), o.bbox[0]),
    )


def _page_plain_text(page) -> str:
    return _strip_nul_bytes("\n".join(_text_object_chars(obj) for obj in _page_text_objects(page)))


def _split_page_by_tables(page, page_tables: list[TableExtract]) -> list[DocumentElement]:
    
    page_height = page.height
    table_ranges = sorted(
        ((page_height - t.bbox[3], page_height - t.bbox[1], t) for t in page_tables),
        key=lambda r: r[0],
    )

    # Exclude any text run whose midpoint falls inside a table's own
    # y-range -- that's the table's own cell text, already captured
    # structurally by Camelot; including it again here would duplicate
    # it as loose prose.
    prose = [
        (obj, _midpoint_y(obj)) for obj in _page_text_objects(page)
        if not any(top <= _midpoint_y(obj) <= bottom for top, bottom, _ in table_ranges)
    ]

    segments: list[DocumentElement] = []
    idx = 0
    for top, _bottom, table in table_ranges:
        before = []
        while idx < len(prose) and prose[idx][1] < top:
            before.append(prose[idx][0])
            idx += 1
        if before:
            text = _reconstruct_paragraphs(_strip_nul_bytes("\n".join(_text_object_chars(o) for o in before)))
            if text.strip():
                segments.append(DocumentElement(kind="text", content=text))
        segments.append(DocumentElement(kind="table", content=table.markdown))

    remaining = [o for o, _mid in prose[idx:]]
    if remaining:
        text = _reconstruct_paragraphs(_strip_nul_bytes("\n".join(_text_object_chars(o) for o in remaining)))
        if text.strip():
            segments.append(DocumentElement(kind="text", content=text))
    return segments


def _pdf_elements(playa_pages: list, tables: list[TableExtract]) -> list[DocumentElement]:
    
    tables_by_page: dict[int, list[TableExtract]] = {}
    for t in tables:
        tables_by_page.setdefault(t.page - 1, []).append(t)

    elements: list[DocumentElement] = []
    prose_buffer: list[str] = []
    for page_index, page in enumerate(playa_pages):
        page_tables = tables_by_page.get(page_index)
        if not page_tables:
            prose_buffer.append(_reconstruct_paragraphs(_page_plain_text(page)))
            continue

        try:
            segments = _split_page_by_tables(page, page_tables)
        except Exception as e:
            
            logging.warning(f"Positional table split failed for page {page_index}: {e}")
            prose_buffer.append(_reconstruct_paragraphs(_page_plain_text(page)))
            segments = [DocumentElement(kind="table", content=t.markdown) for t in page_tables]

        for seg in segments:
            if seg.kind == "text":
                prose_buffer.append(seg.content)
                continue
            if prose_buffer:
                elements.append(DocumentElement(kind="text", content="\n\n".join(prose_buffer)))
                prose_buffer = []
            elements.append(seg)

    if prose_buffer:
        elements.append(DocumentElement(kind="text", content="\n\n".join(prose_buffer)))
    return elements


def extract_pdf(raw_bytes: bytes) -> ExtractionResult:
    tmp_path = _spool_to_tempfile(raw_bytes, ".pdf")
    author, doc_created_at = _read_pdf_metadata(tmp_path)
    try:
        import playa

        with playa.open(str(tmp_path)) as pdf:
            playa_pages = list(pdf.pages)
            native_text = "\n".join(_page_plain_text(p) for p in playa_pages)
            ocr_used = len(native_text.strip()) < MIN_NATIVE_TEXT_CHARS

            if ocr_used:
                
                tables: list[TableExtract] = []
                elements: list[DocumentElement] = []
            else:
                try:
                    tables = _extract_tables_camelot(str(tmp_path))
                except Exception as e:
                    
                    logging.warning(f"Table extraction failed for {tmp_path}: {e}")
                    tables = []
                elements = _pdf_elements(playa_pages, tables)
    finally:
        tmp_path.unlink(missing_ok=True)

    text = _reconstruct_paragraphs(_ocr_pdf(raw_bytes)) if ocr_used else _reconstruct_paragraphs(native_text)
    if ocr_used:
        elements = [DocumentElement(kind="text", content=text)]

    return ExtractionResult(
        text=text, ocr_used=ocr_used, author=author, doc_created_at=doc_created_at,
        tables=tables, elements=elements,
    )


def _ocr_pdf(raw_bytes: bytes) -> str:
    from pdf2image import convert_from_bytes
    import pytesseract

    images = convert_from_bytes(raw_bytes)
    return _strip_nul_bytes("\n".join(pytesseract.image_to_string(image) for image in images))


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
                markdown=_strip_nul_bytes(table.df.to_markdown(index=False)),
                bbox=table._bbox,
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
        text = _strip_nul_bytes("\n".join(doc.page_content for doc in Docx2txtLoader(str(tmp_path)).load()))

        document = python_docx.Document(str(tmp_path))

        # Docx2txtLoader doesn't surface core_properties; read those via
        # python-docx directly.
        props = document.core_properties
        author = _strip_nul_bytes(props.author) if props.author else None
        doc_created_at = props.created

        elements = _docx_elements(document)
        tables = [
            TableExtract(page=index, markdown=el.content)
            for index, el in enumerate((e for e in elements if e.kind == "table"), start=1)
        ]
    finally:
        tmp_path.unlink(missing_ok=True)

    return ExtractionResult(
        text=text, ocr_used=False, author=author, doc_created_at=doc_created_at,
        tables=tables, elements=elements,
    )


def _docx_elements(document: DocxDocument) -> list[DocumentElement]:
    
    elements: list[DocumentElement] = []
    prose_buffer: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = _strip_nul_bytes(DocxParagraph(child, document).text.strip())
            if text:
                prose_buffer.append(text)
        elif child.tag == qn("w:tbl"):
            table = DocxTable(child, document)
            rows = [[_strip_nul_bytes(cell.text.strip()) for cell in row.cells] for row in table.rows]
            if len(rows) < 2 or any(len(row) < 2 for row in rows):
                continue
            if prose_buffer:
                elements.append(DocumentElement(kind="text", content="\n\n".join(prose_buffer)))
                prose_buffer = []
            elements.append(DocumentElement(kind="table", content=_rows_to_markdown(rows)))
    if prose_buffer:
        elements.append(DocumentElement(kind="text", content="\n\n".join(prose_buffer)))
    return elements


def _rows_to_markdown(rows: list[list[str]]) -> str:
    header, *body = rows
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)
