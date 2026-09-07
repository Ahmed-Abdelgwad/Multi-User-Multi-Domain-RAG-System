from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from src.auth.providers.oidc import OIDCProvider
from src.auth.providers.base import ExternalIdentity


def test_sso_login_not_configured_returns_501(client: TestClient):
    # No OIDC_* settings configured in the test environment, so the pool has
    # no registered client -- should fail loudly, not silently proceed.
    response = client.get("/auth/sso/internal/login", follow_redirects=False)
    assert response.status_code == 501


def test_sso_callback_jit_provisions_user_with_zero_roles(client: TestClient, monkeypatch):
    identity = ExternalIdentity(subject="idp-subject-1", email="sso.user@example.com", given_name="SSO", family_name="User")
    monkeypatch.setattr(OIDCProvider, "handle_callback", AsyncMock(return_value=identity))

    response = client.get("/auth/sso/internal/callback")
    assert response.status_code == 200
    token = response.json()["access_token"]

    me_response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "sso.user@example.com"

    domains_response = client.get("/users/me/domains", headers={"Authorization": f"Bearer {token}"})
    assert domains_response.status_code == 200
    assert domains_response.json() == []


def test_sso_callback_is_idempotent_for_same_email(client: TestClient, monkeypatch):
    identity = ExternalIdentity(subject="idp-subject-2", email="repeat.user@example.com")
    monkeypatch.setattr(OIDCProvider, "handle_callback", AsyncMock(return_value=identity))

    first = client.get("/auth/sso/internal/callback")
    second = client.get("/auth/sso/internal/callback")
    assert first.status_code == 200
    assert second.status_code == 200

    first_me = client.get("/users/me", headers={"Authorization": f"Bearer {first.json()['access_token']}"})
    second_me = client.get("/users/me", headers={"Authorization": f"Bearer {second.json()['access_token']}"})
    assert first_me.json()["id"] == second_me.json()["id"]


def test_sso_callback_rejects_cross_pool_email_reuse(client: TestClient, monkeypatch):
    identity = ExternalIdentity(subject="idp-subject-3", email="cross.pool@example.com")
    monkeypatch.setattr(OIDCProvider, "handle_callback", AsyncMock(return_value=identity))

    internal_response = client.get("/auth/sso/internal/callback")
    assert internal_response.status_code == 200

    external_response = client.get("/auth/sso/external/callback")
    assert external_response.status_code == 401
