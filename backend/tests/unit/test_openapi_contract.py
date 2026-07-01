"""The OpenAPI schema documents the full v1 surface and the committed copy never drifts (§10)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.config.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED_SCHEMA = REPO_ROOT / "contracts" / "openapi" / "openapi.json"


def test_openapi_documents_the_v1_surface() -> None:
    client = TestClient(create_app(Settings(_env_file=None)))
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    paths = set(response.json()["paths"])
    expected = {
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/connectors",
        "/api/v1/ingestion/invoices",
        "/api/v1/ingestion/usage-events",
        "/api/v1/reconciliations",
        "/api/v1/reconciliations/{reconciliation_id}",
        "/api/v1/findings",
        "/api/v1/findings/{finding_id}",
        "/api/v1/findings/{finding_id}/review",
        "/api/v1/findings/{finding_id}/confirm",
        "/api/v1/findings/{finding_id}/dismiss",
        "/api/v1/findings/{finding_id}/recover",
        "/api/v1/jobs/{job_id}",
        "/api/v1/webhooks/{connector_id}",
    }
    assert expected <= paths


def test_committed_schema_matches_the_app() -> None:
    # The drift guard's core assertion, runnable locally (CI runs the exporter --check).
    assert COMMITTED_SCHEMA.exists(), "run: uv run python ../ops/scripts/export_openapi.py"
    committed = json.loads(COMMITTED_SCHEMA.read_text(encoding="utf-8"))
    app = create_app(Settings(_env_file=None))
    assert committed == app.openapi()
