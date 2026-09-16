from fastapi.testclient import TestClient

def test_get_current_user(client: TestClient, auth_headers):
    response = client.get("/users/me", headers=auth_headers)
    assert response.status_code == 200
    user_data = response.json()
    assert "email" in user_data
    assert "first_name" in user_data
    assert "last_name" in user_data
    assert "is_platform_admin" in user_data
    assert "password_hash" not in user_data

def test_change_password(client: TestClient, auth_headers):
    # Change password
    response = client.put(
        "/users/change-password",
        headers=auth_headers,
        json={
            "current_password": "testpassword123",
            "new_password": "newpassword123",
            "new_password_confirm": "newpassword123"
        }
    )
    assert response.status_code == 200

    # Try logging in with new password
    login_response = client.post(
        "/auth/token",
        data={
            "username": "test.user@example.com",
            "password": "newpassword123",
            "grant_type": "password"
        }
    )
    assert login_response.status_code == 200

def test_password_change_validation(client: TestClient, auth_headers):
    # Test wrong current password
    response = client.put(
        "/users/change-password",
        headers=auth_headers,
        json={
            "current_password": "wrongpassword",
            "new_password": "newpassword123",
            "new_password_confirm": "newpassword123"
        }
    )
    assert response.status_code == 401

    # Test password mismatch
    response = client.put(
        "/users/change-password",
        headers=auth_headers,
        json={
            "current_password": "testpassword123",
            "new_password": "newpassword123",
            "new_password_confirm": "differentpassword123"
        }
    )
    assert response.status_code == 400

def test_get_current_user_domains_empty_by_default(client: TestClient, auth_headers):
    response = client.get("/users/me/domains", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_get_current_user_domains_lists_memberships(client: TestClient, platform_admin_headers):
    create_response = client.post(
        "/domains/",
        headers=platform_admin_headers,
        json={"name": "membership-domain", "description": "test"},
    )
    assert create_response.status_code == 201

    response = client.get("/users/me/domains", headers=platform_admin_headers)
    assert response.status_code == 200
    memberships = response.json()
    assert len(memberships) == 1
    assert memberships[0]["domain_name"] == "membership-domain"
    assert memberships[0]["role"] == "domain_admin"


def test_list_users_requires_platform_admin(client: TestClient, auth_headers, platform_admin_headers):
    response = client.get("/users/", headers=auth_headers)
    assert response.status_code == 403

    response = client.get("/users/", headers=platform_admin_headers)
    assert response.status_code == 200
    assert any(u["email"].startswith("admin-") for u in response.json())


def _current_user_id(client: TestClient, headers) -> str:
    return client.get("/users/me", headers=headers).json()["id"]


def test_set_platform_admin_requires_platform_admin(client: TestClient, auth_headers, platform_admin_headers):
    target_id = _current_user_id(client, auth_headers)

    response = client.put(f"/users/{target_id}/platform-admin", headers=auth_headers, json={"is_platform_admin": True})

    assert response.status_code == 403


def test_platform_admin_can_grant_and_revoke_admin(client: TestClient, auth_headers, platform_admin_headers):
    target_id = _current_user_id(client, auth_headers)

    response = client.put(f"/users/{target_id}/platform-admin", headers=platform_admin_headers, json={"is_platform_admin": True})
    assert response.status_code == 200
    assert response.json()["is_platform_admin"] is True

    response = client.put(f"/users/{target_id}/platform-admin", headers=platform_admin_headers, json={"is_platform_admin": False})
    assert response.status_code == 200
    assert response.json()["is_platform_admin"] is False


def test_platform_admin_cannot_modify_own_status(client: TestClient, platform_admin_headers):
    self_id = _current_user_id(client, platform_admin_headers)

    response = client.put(f"/users/{self_id}/platform-admin", headers=platform_admin_headers, json={"is_platform_admin": False})

    assert response.status_code == 400


def test_user_endpoints_authorization(client: TestClient):
    # Try accessing user endpoints without auth
    response = client.get("/users/me")
    assert response.status_code == 401

    response = client.put(
        "/users/change-password",
        json={
            "current_password": "testpassword123",
            "new_password": "newpassword123",
            "new_password_confirm": "newpassword123"
        }
    )
    assert response.status_code == 401 