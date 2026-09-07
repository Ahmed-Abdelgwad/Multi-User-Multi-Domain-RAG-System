import pytest
from src.chunking import chunker
from src.entities.enums import ChunkContentType


def test_split_into_paragraphs_drops_empties():
    text = "Para one.\n\n\n\nPara two.\n\n   \n\nPara three."
    assert chunker.split_into_paragraphs(text) == ["Para one.", "Para two.", "Para three."]


def test_group_paragraphs_g2_o1_overlaps_consecutive_chunks():
    # The paper's own formal spec (Table 2: G=2, O=1) -- each paragraph
    # (except the very first/last) should appear in exactly two chunks.
    paragraphs = ["p0", "p1", "p2", "p3"]

    groups = chunker.group_paragraphs(paragraphs, paragraphs_per_chunk=2, overlap=1)

    assert groups == ["p0\n\np1", "p1\n\np2", "p2\n\np3"]


def test_group_paragraphs_single_paragraph_still_produces_one_chunk():
    groups = chunker.group_paragraphs(["only one"], paragraphs_per_chunk=2, overlap=1)
    assert groups == ["only one"]


def test_group_paragraphs_empty_input_returns_no_chunks():
    assert chunker.group_paragraphs([], paragraphs_per_chunk=2, overlap=1) == []


def test_group_paragraphs_rejects_overlap_not_smaller_than_group_size():
    with pytest.raises(ValueError):
        chunker.group_paragraphs(["p0", "p1"], paragraphs_per_chunk=2, overlap=2)


def test_group_paragraphs_rejects_zero_group_size():
    with pytest.raises(ValueError):
        chunker.group_paragraphs(["p0"], paragraphs_per_chunk=0, overlap=0)


def test_strip_table_appendix_removes_markdown_appendix():
    text = "Body paragraph.\n\n[TABLE from page 1]\n| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert chunker.strip_table_appendix(text) == "Body paragraph."


def test_strip_table_appendix_no_op_when_no_tables():
    text = "Body paragraph.\n\nAnother paragraph."
    assert chunker.strip_table_appendix(text) == text


def test_build_chunks_folds_in_tables_as_atomic_chunks_after_text():
    text = "Para one.\n\nPara two.\n\n[TABLE from page 1]\n| a | b |\n| --- | --- |\n| 1 | 2 |"
    tables = [{"page": 1, "markdown": "| a | b |\n| --- | --- |\n| 1 | 2 |"}]

    chunks = chunker.build_chunks(text, tables, paragraphs_per_chunk=2, overlap=1)

    assert [c.content_type for c in chunks] == [ChunkContentType.TEXT, ChunkContentType.TABLE]
    assert chunks[0].content == "Para one.\n\nPara two."
    assert chunks[1].content == tables[0]["markdown"]


def test_build_chunks_no_text_and_no_tables_returns_empty():
    assert chunker.build_chunks("", None, paragraphs_per_chunk=2, overlap=1) == []


def test_build_chunks_table_never_split_even_if_large():
    huge_table_markdown = "| a |\n| --- |\n" + "\n".join(f"| {i} |" for i in range(500))
    tables = [{"page": 1, "markdown": huge_table_markdown}]

    chunks = chunker.build_chunks("", tables, paragraphs_per_chunk=2, overlap=1)

    assert len(chunks) == 1
    assert chunks[0].content_type == ChunkContentType.TABLE
    assert chunks[0].content == huge_table_markdown
