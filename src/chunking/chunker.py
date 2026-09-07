from dataclasses import dataclass
from src.entities.enums import ChunkContentType

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
    
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def group_paragraphs(paragraphs: list[str], paragraphs_per_chunk: int, overlap: int) -> list[str]:
    
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
