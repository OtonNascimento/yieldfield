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


def test_shutdown_disposes_the_process_engine(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Graceful shutdown releases pooled OLTP connections (audit PR-5).
    from yieldfield.api.v1.dependencies import database

    calls: list[str] = []
    monkeypatch.setattr(database, "dispose_engine", lambda: calls.append("disposed"))
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert calls == []  # nothing disposed while serving
    assert calls == ["disposed"]
