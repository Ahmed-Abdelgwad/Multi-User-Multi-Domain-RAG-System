from io import BytesIO
from uuid import uuid4, UUID
import pytest
from fastapi.testclient import TestClient
from src.entities.enums import DomainRole
from src.ontology import service as ontology_service, models as ontology_models
from src.extraction import service as extraction_service, extractor


@pytest.fixture(autouse=True)
def _stub_reextraction(monkeypatch):
    monkeypatch.setattr(ontology_service, "_enqueue_reextraction", lambda domain_id: None)


def _create_domain(client: TestClient, headers, name=None):
    return client.post("/domains/", headers=headers, json={"name": name or f"domain-{uuid4()}", "description": "t"})


def _seed_graph(db_session, domain_id, admin_id):
    """Creates a schema + one chunk on a fake document, then runs the
    extraction service directly against the shared test session (Celery
    isn't running under plain pytest, same rationale as the other e2e
    suites) to produce a real node/edge/link graph to query.
    """
    from src.entities.document import Document
    from src.entities.chunk import Chunk
    from src.entities.enums import DocumentSourceType, DocumentStatus, ChunkContentType

    domain_id = UUID(str(domain_id))
    schema = ontology_service.create_schema_version(
        db_session, domain_id,
        ontology_models.OntologySchemaCreate(
            node_types=["person", "organization"],
            relation_types=[{"name": "works_at", "source_type": "person", "target_type": "organization"}],
        ),
        admin_id,
    )
    document = Document(
        id=uuid4(), domain_id=domain_id, source_type=DocumentSourceType.PDF,
        filename="r.pdf", storage_key="k", status=DocumentStatus.READY, uploaded_by=admin_id,
    )
    db_session.add(document)
    db_session.commit()
    chunk = Chunk(
        id=uuid4(), document_id=document.id, domain_id=domain_id,
        content="Alice works at Acme.", content_type=ChunkContentType.TEXT, chunk_index=0, is_active=True,
    )
    db_session.add(chunk)
    db_session.commit()

    alice = extractor.ExtractedEntity(type="person", name="Alice")
    acme = extractor.ExtractedEntity(type="organization", name="Acme")
    # Stub the real model call, then run extraction for real against the DB.
    import src.extraction.extractor as extractor_module
    original_extract = extractor_module.extract
    extractor_module.extract = lambda text, node_types, relation_types: extractor.ExtractionOutput(
        entities=[alice, acme],
        triples=[extractor.ExtractedTriple(subject=alice, predicate="works_at", object=acme)],
    )
    try:
        extraction_service.process_extract_entities_for_chunk(db_session, chunk, schema, "test-extractor-v1")
        db_session.commit()
    finally:
        extractor_module.extract = original_extract

    return chunk


def test_domain_admin_can_list_graph_nodes_and_edges(client: TestClient, platform_admin_headers, db_session):
    domain_response = _create_domain(client, platform_admin_headers, name="graph-domain")
    domain_id = domain_response.json()["id"]
    from src.entities.user import User
    admin = db_session.query(User).filter(User.is_platform_admin.is_(True)).first()

    _seed_graph(db_session, domain_id, admin.id)

    nodes_response = client.get(f"/domains/{domain_id}/graph/nodes", headers=platform_admin_headers)
    assert nodes_response.status_code == 200
    names = {n["name"] for n in nodes_response.json()}
    assert names == {"Alice", "Acme"}

    edges_response = client.get(f"/domains/{domain_id}/graph/edges", headers=platform_admin_headers)
    assert edges_response.status_code == 200
    edges = edges_response.json()
    assert len(edges) == 1
    assert edges[0]["predicate"] == "works_at"
    assert edges[0]["mention_count"] == 1


def test_bidirectional_lookup_chunk_to_graph_and_back(client: TestClient, platform_admin_headers, db_session):
    from src.entities.user import User

    domain_id = _create_domain(client, platform_admin_headers, name="graph-domain-bidir").json()["id"]
    admin = db_session.query(User).filter(User.is_platform_admin.is_(True)).first()
    chunk = _seed_graph(db_session, domain_id, admin.id)

    nodes_for_chunk = client.get(
        f"/domains/{domain_id}/graph/chunks/{chunk.id}/nodes", headers=platform_admin_headers
    ).json()
    assert {n["name"] for n in nodes_for_chunk} == {"Alice", "Acme"}

    edges_for_chunk = client.get(
        f"/domains/{domain_id}/graph/chunks/{chunk.id}/edges", headers=platform_admin_headers
    ).json()
    assert len(edges_for_chunk) == 1
    edge_id = edges_for_chunk[0]["id"]
    node_id = next(n["id"] for n in nodes_for_chunk if n["name"] == "Alice")

    chunks_for_edge = client.get(
        f"/domains/{domain_id}/graph/edges/{edge_id}/chunks", headers=platform_admin_headers
    ).json()
    assert chunks_for_edge == [str(chunk.id)]

    chunks_for_node = client.get(
        f"/domains/{domain_id}/graph/nodes/{node_id}/chunks", headers=platform_admin_headers
    ).json()
    assert chunks_for_node == [str(chunk.id)]


def test_reader_can_list_graph_nodes(client: TestClient, platform_admin_headers, make_user_with_role, db_session):
    from src.entities.user import User

    domain_id = _create_domain(client, platform_admin_headers, name="graph-domain-reader").json()["id"]
    admin = db_session.query(User).filter(User.is_platform_admin.is_(True)).first()
    _seed_graph(db_session, domain_id, admin.id)
    reader_headers, _ = make_user_with_role(domain_id, DomainRole.READER)

    response = client.get(f"/domains/{domain_id}/graph/nodes", headers=reader_headers)

    assert response.status_code == 200


def test_user_without_role_cannot_read_graph(client: TestClient, platform_admin_headers, auth_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="graph-domain-norole").json()["id"]

    response = client.get(f"/domains/{domain_id}/graph/nodes", headers=auth_headers)

    assert response.status_code == 403
