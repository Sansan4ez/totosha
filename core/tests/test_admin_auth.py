"""Tests for service-level authentication on every admin API route."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import admin_api


TEST_TOKEN = "test-admin-token"


def _client(monkeypatch, tmp_path, token=TEST_TOKEN) -> TestClient:
    secret_path = tmp_path / "admin_api_token"
    if token is not None:
        secret_path.write_text(token)

    monkeypatch.setenv("ADMIN_API_TOKEN_FILE", str(secret_path))
    admin_api._admin_token.cache_clear()

    app = FastAPI()
    app.include_router(admin_api.router)
    return TestClient(app)


def test_admin_route_rejects_missing_token(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.get("/api/admin/config")

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorized"}


def test_admin_route_rejects_wrong_token(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.get(
            "/api/admin/config",
            headers={"X-Admin-Token": "wrong"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorized"}


def test_admin_route_accepts_correct_token(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.get(
            "/api/admin/config",
            headers={"X-Admin-Token": TEST_TOKEN},
        )

    assert response.status_code == 200
    assert "access" in response.json()


def test_admin_auth_fails_closed_without_secret(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, token=None) as client:
        response = client.get("/api/admin/config")

    assert response.status_code == 503
    assert response.json() == {"detail": "admin auth not configured"}


def test_panel_password_is_not_accepted_as_api_token(monkeypatch, tmp_path):
    """The panel's basic-auth secret must not authenticate the service API."""
    panel_password = tmp_path / "admin_password"
    panel_password.write_text("panel-basic-auth-password")
    monkeypatch.setenv("ADMIN_PASSWORD_FILE", str(panel_password))

    with _client(monkeypatch, tmp_path) as client:
        response = client.get(
            "/api/admin/config",
            headers={"X-Admin-Token": "panel-basic-auth-password"},
        )

    assert response.status_code == 401


def test_all_admin_routes_have_router_level_auth():
    assert any(
        dependency.dependency is admin_api.require_admin
        for dependency in admin_api.router.dependencies
    )
