"""Paragraph Group Chunking (PGC), spec 2.4 -- chosen per the section-2
plan's literature review (arXiv:2603.06976's own benchmark, cross-checked
against a second, independently peer-reviewed reproduction, SIGIR 2026
arXiv:2602.16974: both agree structure-based/paragraph-family chunking is
the right call for this project's in-corpus, multi-domain retrieval shape).

Pure text-structure logic, no DB/embedding-model dependency -- kept
separate from `service.py` so it's unit-testable on its own, same
separation `ingestion/extraction.py` uses relative to `ingestion/service.py`.
"""
from dataclasses import dataclass
from src.entities.enums import ChunkContentType

# The extraction pipeline (src/ingestion/extraction.py) appends a
# Markdown rendering of each Camelot/python-docx table onto
# `Document.extracted_text`, behind this exact marker, so table content
# isn't lost even independent of chunking. PGC must not re-chunk that
# appendix as running text -- each table already exists as its own
# structured entry on `Document.tables_extracted` and becomes exactly one
# atomic chunk (see `_table_chunks` below), never merged/split. Splitting
# on this marker recovers the plain body text PGC should actually chunk.
TABLE_APPENDIX_MARKER = "\n\n[TABLE from page "


@dataclass(frozen=True)
class ChunkCandidate:
    content: str
    content_type: ChunkContentType


def strip_table_appendix(text: str) -> str:
    """Returns `text` with the trailing table-markdown appendix (if any)
    removed, so PGC only sees the document's real prose.
    """
    return text.split(TABLE_APPENDIX_MARKER, 1)[0]


def split_into_paragraphs(text: str) -> list[str]:
    """Splits on blank lines (one or more consecutive newlines), the same
    boundary `extraction.py`'s PyPDFLoader/Docx2txtLoader output respects
    for well-formed prose. Empty/whitespace-only paragraphs are dropped.
    """
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def group_paragraphs(paragraphs: list[str], paragraphs_per_chunk: int, overlap: int) -> list[str]:
    """PGC's core: group `paragraphs_per_chunk` (G) consecutive paragraphs
    per chunk, advancing by `G - overlap` (O) paragraphs each step so
    consecutive chunks share `overlap` paragraphs. Matches the paper's
    formal spec (Table 2: G=2, O=1 by default -- see
    `DomainIngestionConfig`'s defaults).
    """
    if not paragraphs:
        return []
    if paragraphs_per_chunk < 1:
        raise ValueError("paragraphs_per_chunk must be >= 1")
    if overlap < 0 or overlap >= paragraphs_per_chunk:
        raise ValueError("overlap must be >= 0 and < paragraphs_per_chunk")

    step = paragraphs_per_chunk - overlap
    groups: list[str] = []
    i = 0
    while i < len(paragraphs):
        group = paragraphs[i:i + paragraphs_per_chunk]
        groups.append("\n\n".join(group))
        if i + paragraphs_per_chunk >= len(paragraphs):
            break
        i += step
    return groups


def _table_chunks(tables: list[dict] | None) -> list[ChunkCandidate]:
    if not tables:
        return []
    return [ChunkCandidate(content=t["markdown"], content_type=ChunkContentType.TABLE) for t in tables]


def build_chunks(
    text: str,
    tables: list[dict] | None,
    paragraphs_per_chunk: int,
    overlap: int,
) -> list[ChunkCandidate]:
    """Full PGC pass for one document: paragraph-group the body text, then
    append each extracted table as its own atomic chunk. Order is text
    chunks first (in document order) then table chunks -- table position
    within the body isn't tracked post-extraction, an accepted MVP
    simplification (noted in the plan).
    """
    body_text = strip_table_appendix(text)
    paragraphs = split_into_paragraphs(body_text)
    text_chunks = [
        ChunkCandidate(content=group, content_type=ChunkContentType.TEXT)
        for group in group_paragraphs(paragraphs, paragraphs_per_chunk, overlap)
    ]
    return text_chunks + _table_chunks(tables)
