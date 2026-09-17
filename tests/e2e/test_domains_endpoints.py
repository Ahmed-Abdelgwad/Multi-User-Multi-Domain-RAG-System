from fastapi.testclient import TestClient
from uuid import uuid4
from src.entities.enums import DomainRole


def _create_domain(client: TestClient, headers, name=None):
    return client.post(
        "/domains/",
        headers=headers,
        json={"name": name or f"domain-{uuid4()}", "description": "test"},
    )


def test_non_platform_admin_cannot_create_domain(client: TestClient, auth_headers):
    response = _create_domain(client, auth_headers)
    assert response.status_code == 403


def test_platform_admin_can_create_domain_and_is_auto_admin(client: TestClient, platform_admin_headers):
    response = _create_domain(client, platform_admin_headers, name="engineering")
    assert response.status_code == 201
    domain = response.json()
    assert domain["name"] == "engineering"
    domain_id = domain["id"]

    # creator was auto-granted domain_admin, so they can list roles
    roles_response = client.get(f"/domains/{domain_id}/roles", headers=platform_admin_headers)
    assert roles_response.status_code == 200
    roles = roles_response.json()
    assert len(roles) == 1
    assert roles[0]["role"] == "domain_admin"


def test_duplicate_domain_name_rejected(client: TestClient, platform_admin_headers):
    _create_domain(client, platform_admin_headers, name="duplicate-name")
    response = _create_domain(client, platform_admin_headers, name="duplicate-name")
    assert response.status_code == 409


def test_reader_can_view_but_not_manage_roles(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="reader-domain").json()["id"]
    reader_headers, _ = make_user_with_role(domain_id, DomainRole.READER)

    get_response = client.get(f"/domains/{domain_id}", headers=reader_headers)
    assert get_response.status_code == 200

    roles_response = client.get(f"/domains/{domain_id}/roles", headers=reader_headers)
    assert roles_response.status_code == 403

    assign_response = client.post(
        f"/domains/{domain_id}/roles",
        headers=reader_headers,
        json={"user_id": str(uuid4()), "role": "reader"},
    )
    assert assign_response.status_code == 403


def test_user_without_role_cannot_view_domain(client: TestClient, platform_admin_headers, auth_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="private-domain").json()["id"]
    response = client.get(f"/domains/{domain_id}", headers=auth_headers)
    assert response.status_code == 403


def test_domain_admin_can_assign_and_revoke_roles(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="assign-domain").json()["id"]
    _, target_user_id = make_user_with_role(uuid4(), DomainRole.READER)  # unrelated domain, just to get a user id

    assign_response = client.post(
        f"/domains/{domain_id}/roles",
        headers=platform_admin_headers,
        json={"user_id": str(target_user_id), "role": "contributor"},
    )
    assert assign_response.status_code == 201
    assert assign_response.json()["role"] == "contributor"

    roles_before_revoke = client.get(f"/domains/{domain_id}/roles", headers=platform_admin_headers).json()
    target_row = next(r for r in roles_before_revoke if r["user_id"] == str(target_user_id))
    assert target_row["user_email"]  # list_domain_roles enriches with the real email, not just a bare UUID

    revoke_response = client.delete(
        f"/domains/{domain_id}/roles/{target_user_id}", headers=platform_admin_headers
    )
    assert revoke_response.status_code == 204

    roles_response = client.get(f"/domains/{domain_id}/roles", headers=platform_admin_headers)
    assert all(r["user_id"] != str(target_user_id) for r in roles_response.json())


def test_roles_lookup_requires_domain_admin(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="lookup-domain-rbac").json()["id"]
    contributor_headers, _ = make_user_with_role(domain_id, DomainRole.CONTRIBUTOR)

    response = client.get(f"/domains/{domain_id}/roles/lookup?email=ex", headers=contributor_headers)

    assert response.status_code == 403


def test_roles_lookup_returns_matching_users(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="lookup-domain").json()["id"]
    unique = uuid4().hex[:8]
    client.post(
        "/auth/",
        json={"email": f"findme-{unique}@example.com", "password": "testpassword123", "first_name": "Find", "last_name": "Me"},
    )

    response = client.get(f"/domains/{domain_id}/roles/lookup?email=findme-{unique}", headers=platform_admin_headers)

    assert response.status_code == 200
    emails = [u["email"] for u in response.json()]
    assert f"findme-{unique}@example.com" in emails


def test_roles_lookup_requires_minimum_query_length(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="lookup-domain-minlen").json()["id"]

    response = client.get(f"/domains/{domain_id}/roles/lookup?email=a", headers=platform_admin_headers)

    assert response.status_code == 422


def test_archived_domain_rejects_new_role_assignment(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="archive-domain").json()["id"]

    archive_response = client.post(f"/domains/{domain_id}/archive", headers=platform_admin_headers)
    assert archive_response.status_code == 200
    assert archive_response.json()["is_archived"] is True

    assign_response = client.post(
        f"/domains/{domain_id}/roles",
        headers=platform_admin_headers,
        json={"user_id": str(uuid4()), "role": "reader"},
    )
    assert assign_response.status_code == 400


def test_non_admin_cannot_archive_domain(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="no-archive-domain").json()["id"]
    reader_headers, _ = make_user_with_role(domain_id, DomainRole.READER)

    response = client.post(f"/domains/{domain_id}/archive", headers=reader_headers)
    assert response.status_code == 403


def test_cannot_hard_delete_a_domain_that_is_not_archived(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="not-archived-domain").json()["id"]

    response = client.delete(f"/domains/{domain_id}", headers=platform_admin_headers)

    assert response.status_code == 400
    assert client.get(f"/domains/{domain_id}", headers=platform_admin_headers).status_code == 200


def test_non_platform_admin_cannot_hard_delete_domain(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="admin-only-delete-domain").json()["id"]
    admin_headers, _ = make_user_with_role(domain_id, DomainRole.ADMIN)
    client.post(f"/domains/{domain_id}/archive", headers=platform_admin_headers)

    response = client.delete(f"/domains/{domain_id}", headers=admin_headers)

    assert response.status_code == 403


def test_platform_admin_can_hard_delete_an_archived_domain(client: TestClient, platform_admin_headers, make_user_with_role):
    domain_id = _create_domain(client, platform_admin_headers, name="deletable-domain").json()["id"]
    make_user_with_role(domain_id, DomainRole.READER)  # extra row that must be cleaned up too
    client.post(f"/domains/{domain_id}/archive", headers=platform_admin_headers)

    response = client.delete(f"/domains/{domain_id}", headers=platform_admin_headers)

    assert response.status_code == 204
    assert client.get(f"/domains/{domain_id}", headers=platform_admin_headers).status_code == 403


def test_delete_all_archived_domains_only_deletes_archived_ones(client: TestClient, platform_admin_headers):
    archived_id = _create_domain(client, platform_admin_headers, name="bulk-archived-domain").json()["id"]
    active_id = _create_domain(client, platform_admin_headers, name="bulk-active-domain").json()["id"]
    client.post(f"/domains/{archived_id}/archive", headers=platform_admin_headers)

    response = client.delete("/domains/", headers=platform_admin_headers)

    assert response.status_code == 200
    deleted_ids = response.json()
    assert archived_id in deleted_ids
    assert active_id not in deleted_ids
    assert client.get(f"/domains/{archived_id}", headers=platform_admin_headers).status_code == 403
    assert client.get(f"/domains/{active_id}", headers=platform_admin_headers).status_code == 200


def test_non_platform_admin_cannot_bulk_delete_archived_domains(client: TestClient, platform_admin_headers):
    domain_id = _create_domain(client, platform_admin_headers, name="bulk-rbac-domain").json()["id"]
    client.post(f"/domains/{domain_id}/archive", headers=platform_admin_headers)

    response = client.delete("/domains/")  # no auth header at all

    assert response.status_code == 401
    assert client.get(f"/domains/{domain_id}", headers=platform_admin_headers).status_code == 200


def test_cross_domain_isolation_reader_cannot_see_other_domains_roles(
    client: TestClient, platform_admin_headers, make_user_with_role
):
    domain_a = _create_domain(client, platform_admin_headers, name="domain-a").json()["id"]
    domain_b = _create_domain(client, platform_admin_headers, name="domain-b").json()["id"]
    reader_headers, _ = make_user_with_role(domain_a, DomainRole.READER)

    # Reader in domain A has no role in domain B at all
    response = client.get(f"/domains/{domain_b}", headers=reader_headers)
    assert response.status_code == 403

    roles_response = client.get(f"/domains/{domain_b}/roles", headers=reader_headers)
    assert roles_response.status_code == 403
