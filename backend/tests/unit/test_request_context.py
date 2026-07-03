"""Request-scoped log context (audit PR-4a): correlation ids on every response and log line."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping, Sequence
from contextlib import contextmanager
from typing import Any

import structlog
from fastapi.testclient import TestClient
from structlog.testing import LogCapture

from yieldfield.api.main import create_app
from yieldfield.config.settings import Settings


@contextmanager
def _capture_logs() -> Iterator[LogCapture]:
    # Entered AFTER create_app(): the app factory calls configure_logging, which would
    # overwrite this capture configuration if applied the other way round.
    captured = LogCapture()
    previous = structlog.get_config()["processors"]
    structlog.configure(processors=[structlog.contextvars.merge_contextvars, captured])
    try:
        yield captured
    finally:
        structlog.configure(processors=previous)


def _http_events(captured: LogCapture) -> list[MutableMapping[str, Any]]:
    return [e for e in captured.entries if e["event"] == "http.request"]


def test_every_response_carries_a_request_id() -> None:
    client = TestClient(create_app(Settings(_env_file=None)))
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_supplied_request_id_is_echoed_and_logged() -> None:
    client = TestClient(create_app(Settings(_env_file=None)))
    with _capture_logs() as captured:
        response = client.get("/api/v1/health", headers={"X-Request-ID": "req-e2e-abc"})
    assert response.headers["X-Request-ID"] == "req-e2e-abc"
    events = _http_events(captured)
    assert events, "the middleware logs one http.request line per request"
    assert events[-1]["request_id"] == "req-e2e-abc"
    assert events[-1]["status"] == 200
    assert events[-1]["method"] == "GET"
    assert events[-1]["path"] == "/api/v1/health"


def test_authenticated_requests_bind_the_tenant_into_the_log_context() -> None:
    from yieldfield.api.v1.dependencies.services import get_connector_store
    from yieldfield.api.v1.dependencies.settings import get_app_settings
    from yieldfield.domain.billing.connector import Connector

    class _EmptyStore:
        def list_for_tenant(self, tenant_id: object) -> Sequence[Connector]:
            return []

    settings = Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"})
    app = create_app(settings)
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_connector_store] = lambda: _EmptyStore()
    client = TestClient(app)
    with _capture_logs() as captured:
        response = client.get("/api/v1/connectors", headers={"Authorization": "Bearer tok-1"})
    assert response.status_code == 200
    events = _http_events(captured)
    assert events[-1]["tenant_id"] == "tenant-1"  # bound by the auth dependency (§11)
