import pytest
from src.chunking import chunker


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


def test_paragraph_group_text_splitter_matches_group_paragraphs():
    splitter = chunker.ParagraphGroupTextSplitter(paragraphs_per_chunk=2, paragraph_overlap=1)

    assert splitter.split_text("p0\n\np1\n\np2") == chunker.group_paragraphs(["p0", "p1", "p2"], 2, 1)


def test_paragraph_group_text_splitter_create_documents_carries_metadata():
    # `create_documents` is LangChain's own, unmodified method -- proves
    # the splitter's `split_text` override is enough for it to work
    # correctly, no custom Document-building method needed.
    splitter = chunker.ParagraphGroupTextSplitter(paragraphs_per_chunk=2, paragraph_overlap=1)

    docs = splitter.create_documents(["Para one.\n\nPara two."], metadatas=[{"content_type": "text"}])

    assert len(docs) == 1
    assert docs[0].page_content == "Para one.\n\nPara two."
    assert docs[0].metadata == {"content_type": "text"}


def test_build_documents_folds_in_tables_as_atomic_documents_in_element_order():
    elements = [
        {"kind": "text", "content": "Para one.\n\nPara two."},
        {"kind": "table", "content": "| a | b |\n| --- | --- |\n| 1 | 2 |"},
        {"kind": "text", "content": "Para three."},
    ]

    docs = chunker.build_documents(elements, paragraphs_per_chunk=2, overlap=1)

    assert [d.metadata["content_type"] for d in docs] == ["text", "table", "text"]
    assert docs[0].page_content == "Para one.\n\nPara two."
    assert docs[1].page_content == "| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert docs[2].page_content == "Para three."


def test_build_documents_no_elements_returns_empty():
    assert chunker.build_documents([], paragraphs_per_chunk=2, overlap=1) == []


def test_build_documents_table_never_split_even_if_large():
    huge_table_markdown = "| a |\n| --- |\n" + "\n".join(f"| {i} |" for i in range(500))
    elements = [{"kind": "table", "content": huge_table_markdown}]

    docs = chunker.build_documents(elements, paragraphs_per_chunk=2, overlap=1)

    assert len(docs) == 1
    assert docs[0].metadata["content_type"] == "table"
    assert docs[0].page_content == huge_table_markdown


def test_build_documents_pgc_does_not_bridge_across_a_table():
    # Each "text" element is paragraph-grouped independently -- PGC must
    # never merge a paragraph from before a table with one from after it
    # into the same chunk, since they're separated by the table's true
    # position in the document.
    elements = [
        {"kind": "text", "content": "Before the table."},
        {"kind": "table", "content": "| a |\n| --- |\n| 1 |"},
        {"kind": "text", "content": "After the table."},
    ]

    docs = chunker.build_documents(elements, paragraphs_per_chunk=2, overlap=1)

    text_docs = [d for d in docs if d.metadata["content_type"] == "text"]
    assert [d.page_content for d in text_docs] == ["Before the table.", "After the table."]
