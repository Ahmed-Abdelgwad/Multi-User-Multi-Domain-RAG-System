from langchain_text_splitters import TextSplitter
from langchain_core.documents import Document
from src.entities.enums import ChunkContentType


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


class ParagraphGroupTextSplitter(TextSplitter):

    def __init__(self, paragraphs_per_chunk: int, paragraph_overlap: int):
        super().__init__(chunk_size=10**9, chunk_overlap=0)
        self.paragraphs_per_chunk = paragraphs_per_chunk
        self.paragraph_overlap = paragraph_overlap

    def split_text(self, text: str) -> list[str]:
        return group_paragraphs(split_into_paragraphs(text), self.paragraphs_per_chunk, self.paragraph_overlap)


def build_documents(elements: list[dict], paragraphs_per_chunk: int, overlap: int) -> list[Document]:

    splitter = ParagraphGroupTextSplitter(paragraphs_per_chunk, overlap)
    documents: list[Document] = []
    atomic_content_types = {"table": ChunkContentType.TABLE, "figure": ChunkContentType.FIGURE}
    for el in elements:
        if el["kind"] in atomic_content_types:
            content_type = atomic_content_types[el["kind"]]
            documents.append(Document(page_content=el["content"], metadata={"content_type": content_type.value}))
        else:
            documents.extend(
                splitter.create_documents([el["content"]], metadatas=[{"content_type": ChunkContentType.TEXT.value}])
            )
    return documents
