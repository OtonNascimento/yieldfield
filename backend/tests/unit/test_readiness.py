"""/ready reports per-dependency connectivity; any failure degrades to 503 (§11, §13)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies import readiness
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings


def _client() -> TestClient:
    # Override the settings dependency so the test never sees a developer's .env values
    # (deterministic database_url/clickhouse_url = None → "skipped").
    settings = Settings(_env_file=None)
    app = create_app(settings)
    app.dependency_overrides[get_app_settings] = lambda: settings
    return TestClient(app, raise_server_exceptions=False)


def test_ready_is_200_when_all_checks_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness, "_check_postgres", lambda settings: "ok")
    monkeypatch.setattr(readiness, "_check_clickhouse", lambda settings: "ok")
    monkeypatch.setattr(readiness, "_check_redis", lambda settings: "ok")
    response = _client().get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"postgres": "ok", "clickhouse": "ok", "redis": "ok"}


def test_ready_degrades_to_503_when_any_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness, "_check_postgres", lambda settings: "ok")
    monkeypatch.setattr(readiness, "_check_clickhouse", lambda settings: "error")
    monkeypatch.setattr(readiness, "_check_redis", lambda settings: "ok")
    response = _client().get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["clickhouse"] == "error"


def test_unconfigured_dependencies_are_skipped_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # database_url/clickhouse_url default to None locally — that's "skipped", not an error.
    monkeypatch.setattr(readiness, "_check_redis", lambda settings: "ok")
    response = _client().get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["postgres"] == "skipped"
    assert response.json()["checks"]["clickhouse"] == "skipped"
