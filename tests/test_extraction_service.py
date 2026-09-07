from uuid import uuid4
from src.entities.domain import Domain
from src.entities.document import Document
from src.entities.chunk import Chunk
from src.entities.graph_node import GraphNode
from src.entities.graph_edge import GraphEdge
from src.entities.chunk_graph_node_link import ChunkGraphNodeLink
from src.entities.chunk_graph_edge_link import ChunkGraphEdgeLink
from src.entities.enums import DocumentSourceType, DocumentStatus, ChunkContentType
from src.ontology import service as ontology_service, models as ontology_models
from src.extraction import service, extractor


def _make_domain_with_schema(db_session, monkeypatch):
    monkeypatch.setattr(ontology_service, "_enqueue_reextraction", lambda domain_id: None)
    domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4())
    db_session.add(domain)
    db_session.commit()
    schema = ontology_service.create_schema_version(
        db_session, domain.id,
        ontology_models.OntologySchemaCreate(
            node_types=["person", "organization"],
            relation_types=[{"name": "works_at", "source_type": "person", "target_type": "organization"}],
        ),
        uuid4(),
    )
    return domain, schema


def _make_chunk(db_session, domain, content="Alice works at Acme.", document=None):
    if document is None:
        document = Document(
            id=uuid4(), domain_id=domain.id, source_type=DocumentSourceType.PDF,
            filename="r.pdf", storage_key="k", status=DocumentStatus.READY, uploaded_by=uuid4(),
        )
        db_session.add(document)
        db_session.commit()
    chunk = Chunk(
        id=uuid4(), document_id=document.id, domain_id=domain.id,
        content=content, content_type=ChunkContentType.TEXT, chunk_index=0, is_active=True,
    )
    db_session.add(chunk)
    db_session.commit()
    return chunk, document


def _stub_extraction(monkeypatch, entities=None, triples=None):
    output = extractor.ExtractionOutput(entities=entities or [], triples=triples or [])
    monkeypatch.setattr(extractor, "extract", lambda text, node_types, relation_types: output)


def test_process_extract_entities_for_chunk_creates_nodes_and_edge(db_session, monkeypatch):
    domain, schema = _make_domain_with_schema(db_session, monkeypatch)
    chunk, _ = _make_chunk(db_session, domain)
    alice = extractor.ExtractedEntity(type="person", name="Alice")
    acme = extractor.ExtractedEntity(type="organization", name="Acme")
    _stub_extraction(
        monkeypatch,
        entities=[alice, acme],
        triples=[extractor.ExtractedTriple(subject=alice, predicate="works_at", object=acme)],
    )

    service.process_extract_entities_for_chunk(db_session, chunk, schema, "test-extractor-v1")
    db_session.commit()

    nodes = db_session.query(GraphNode).filter(GraphNode.domain_id == domain.id).all()
    assert {n.name for n in nodes} == {"Alice", "Acme"}
    assert all(n.ontology_version == schema.version for n in nodes)
    assert all(n.extractor_model_version == "test-extractor-v1" for n in nodes)

    edges = db_session.query(GraphEdge).filter(GraphEdge.domain_id == domain.id).all()
    assert len(edges) == 1
    assert edges[0].predicate == "works_at"
    assert edges[0].mention_count == 1

    node_links = db_session.query(ChunkGraphNodeLink).filter(ChunkGraphNodeLink.chunk_id == chunk.id).all()
    edge_links = db_session.query(ChunkGraphEdgeLink).filter(ChunkGraphEdgeLink.chunk_id == chunk.id).all()
    assert len(node_links) == 2
    assert len(edge_links) == 1


def test_process_extract_entities_for_chunk_dedupes_case_insensitively_across_chunks(db_session, monkeypatch):
    domain, schema = _make_domain_with_schema(db_session, monkeypatch)
    chunk_a, document = _make_chunk(db_session, domain, content="alice works at Acme.")
    chunk_b, _ = _make_chunk(db_session, domain, content="ALICE works at Acme Corp.", document=document)

    alice_lower = extractor.ExtractedEntity(type="person", name="alice")
    alice_upper = extractor.ExtractedEntity(type="person", name="ALICE")
    acme = extractor.ExtractedEntity(type="organization", name="Acme")

    monkeypatch.setattr(
        extractor, "extract",
        lambda text, node_types, relation_types: (
            extractor.ExtractionOutput(entities=[alice_lower, acme], triples=[
                extractor.ExtractedTriple(subject=alice_lower, predicate="works_at", object=acme)
            ]) if text == chunk_a.content else
            extractor.ExtractionOutput(entities=[alice_upper, acme], triples=[
                extractor.ExtractedTriple(subject=alice_upper, predicate="works_at", object=acme)
            ])
        ),
    )

    service.process_extract_entities_for_chunk(db_session, chunk_a, schema, "v1")
    service.process_extract_entities_for_chunk(db_session, chunk_b, schema, "v1")
    db_session.commit()

    person_nodes = db_session.query(GraphNode).filter(GraphNode.domain_id == domain.id, GraphNode.type == "person").all()
    assert len(person_nodes) == 1
    assert person_nodes[0].name == "alice"  # first-seen casing kept

    edges = db_session.query(GraphEdge).filter(GraphEdge.domain_id == domain.id).all()
    assert len(edges) == 1
    assert edges[0].mention_count == 2  # asserted from 2 distinct chunks


def test_reprocessing_same_chunk_does_not_inflate_mention_count(db_session, monkeypatch):
    domain, schema = _make_domain_with_schema(db_session, monkeypatch)
    chunk, _ = _make_chunk(db_session, domain)
    alice = extractor.ExtractedEntity(type="person", name="Alice")
    acme = extractor.ExtractedEntity(type="organization", name="Acme")
    _stub_extraction(
        monkeypatch, entities=[alice, acme],
        triples=[extractor.ExtractedTriple(subject=alice, predicate="works_at", object=acme)],
    )

    service.process_extract_entities_for_chunk(db_session, chunk, schema, "v1")
    service.process_extract_entities_for_chunk(db_session, chunk, schema, "v1")  # re-run, same chunk
    db_session.commit()

    edges = db_session.query(GraphEdge).filter(GraphEdge.domain_id == domain.id).all()
    assert len(edges) == 1
    assert edges[0].mention_count == 1  # not 2 -- same chunk re-linked, not double-counted

    node_links = db_session.query(ChunkGraphNodeLink).filter(ChunkGraphNodeLink.chunk_id == chunk.id).all()
    assert len(node_links) == 2  # not 4


def test_description_accumulates_without_duplicating_identical_text(db_session, monkeypatch):
    domain, schema = _make_domain_with_schema(db_session, monkeypatch)
    chunk_a, document = _make_chunk(db_session, domain, content="Alice is a person.")
    chunk_b, _ = _make_chunk(db_session, domain, content="Alice works remotely.", document=document)

    alice = extractor.ExtractedEntity(type="person", name="Alice")
    monkeypatch.setattr(
        extractor, "extract",
        lambda text, node_types, relation_types: extractor.ExtractionOutput(entities=[alice], triples=[]),
    )

    service.process_extract_entities_for_chunk(db_session, chunk_a, schema, "v1")
    service.process_extract_entities_for_chunk(db_session, chunk_b, schema, "v1")
    db_session.commit()

    node = db_session.query(GraphNode).filter(GraphNode.domain_id == domain.id).first()
    assert "Alice is a person." in node.description
    assert "Alice works remotely." in node.description


def test_process_extract_entities_for_document_skips_when_no_active_ontology(db_session, monkeypatch):
    domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4())
    db_session.add(domain)
    db_session.commit()
    chunk, document = _make_chunk(db_session, domain)

    # Should not raise, and must not touch entities_extracted_at.
    service.process_extract_entities_for_document(db_session, document.id)

    db_session.refresh(chunk)
    assert chunk.entities_extracted_at is None


def test_process_extract_entities_for_document_marks_chunks_extracted(db_session, monkeypatch):
    domain, schema = _make_domain_with_schema(db_session, monkeypatch)
    chunk, document = _make_chunk(db_session, domain)
    _stub_extraction(monkeypatch, entities=[], triples=[])

    service.process_extract_entities_for_document(db_session, document.id)

    db_session.refresh(chunk)
    assert chunk.entities_extracted_at is not None


def test_process_extract_entities_for_chunk_handles_repeated_entity_mention_in_same_chunk(db_session, monkeypatch):
    # Regression test for a real bug found live against a real CV: the
    # model can return multiple distinct spans for the same repeated
    # mention within one chunk (e.g. a skill name used twice in one
    # bullet list). Both resolve to the same GraphNode via
    # `_get_or_touch_node`'s dedup, but linking each to the chunk without
    # an intermediate flush raised psycopg2.errors.UniqueViolation on
    # `uq_chunk_graph_node_links_pair` (SQLAlchemy's autoflush is off --
    # see database/core.py -- so the second link's exists-check couldn't
    # see the first one's still-pending insert).
    domain, schema = _make_domain_with_schema(db_session, monkeypatch)
    chunk, _ = _make_chunk(db_session, domain, content="Alice, Alice, Alice.")
    mention_1 = extractor.ExtractedEntity(type="person", name="Alice")
    mention_2 = extractor.ExtractedEntity(type="person", name="Alice")
    monkeypatch.setattr(
        extractor, "extract",
        lambda text, node_types, relation_types: extractor.ExtractionOutput(
            entities=[mention_1, mention_2], triples=[]
        ),
    )

    service.process_extract_entities_for_chunk(db_session, chunk, schema, "v1")  # must not raise
    db_session.commit()

    nodes = db_session.query(GraphNode).filter(GraphNode.domain_id == domain.id).all()
    assert len(nodes) == 1
    links = db_session.query(ChunkGraphNodeLink).filter(ChunkGraphNodeLink.chunk_id == chunk.id).all()
    assert len(links) == 1


def test_process_extract_entities_for_document_commits_per_chunk_not_all_or_nothing(db_session, monkeypatch):
    # Regression test for a real bug found live on a 25-chunk document:
    # one chunk's failure used to roll back every other chunk's
    # already-successful extraction in the same pass, since the whole
    # document was one transaction. Now each chunk commits independently.
    domain, schema = _make_domain_with_schema(db_session, monkeypatch)
    document = Document(
        id=uuid4(), domain_id=domain.id, source_type=DocumentSourceType.PDF,
        filename="r.pdf", storage_key="k", status=DocumentStatus.READY, uploaded_by=uuid4(),
    )
    db_session.add(document)
    db_session.commit()
    chunk_ok, _ = _make_chunk(db_session, domain, content="Alice works at Acme.", document=document)
    chunk_bad, _ = _make_chunk(db_session, domain, content="Bob works at Beta.", document=document)

    alice = extractor.ExtractedEntity(type="person", name="Alice")
    acme = extractor.ExtractedEntity(type="organization", name="Acme")

    def _extract_stub(text, node_types, relation_types):
        if text == chunk_bad.content:
            raise RuntimeError("simulated model failure")
        return extractor.ExtractionOutput(entities=[alice, acme], triples=[])

    monkeypatch.setattr(extractor, "extract", _extract_stub)

    service.process_extract_entities_for_document(db_session, document.id)

    db_session.refresh(chunk_ok)
    db_session.refresh(chunk_bad)
    assert chunk_ok.entities_extracted_at is not None
    assert chunk_bad.entities_extracted_at is None  # left NULL so the next batch tick retries just this one

    nodes = db_session.query(GraphNode).filter(GraphNode.domain_id == domain.id).all()
    assert {n.name for n in nodes} == {"Alice", "Acme"}  # chunk_ok's work survived chunk_bad's failure


def test_process_extract_entities_for_document_skips_already_extracted_chunks(db_session, monkeypatch):
    domain, schema = _make_domain_with_schema(db_session, monkeypatch)
    chunk, document = _make_chunk(db_session, domain)

    calls = []
    monkeypatch.setattr(
        extractor, "extract",
        lambda text, node_types, relation_types: (calls.append(text), extractor.ExtractionOutput())[1],
    )

    service.process_extract_entities_for_document(db_session, document.id)
    service.process_extract_entities_for_document(db_session, document.id)  # second run: nothing left to do

    assert len(calls) == 1
