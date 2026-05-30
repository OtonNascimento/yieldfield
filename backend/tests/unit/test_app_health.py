"""The API boots and the health contract responds (§10). No external I/O."""

from __future__ import annotations

from fastapi.testclient import TestClient

from yieldfield.api.main import create_app


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "yieldfield-api"


def test_unknown_route_uses_error_envelope() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    # The standard envelope: { error: { code, message, details } } (§10).
    assert "error" in response.json()
    assert response.json()["error"]["code"] == "http_404"
