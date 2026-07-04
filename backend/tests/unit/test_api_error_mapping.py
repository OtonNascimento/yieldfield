"""Typed exceptions map onto the standard error envelope (spec §5.4)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.errors.exceptions import (
    IngestionDisabledError,
    InvalidCursorError,
    InvalidWebhookSignatureError,
    UnauthorizedError,
    WebhookPayloadTooLargeError,
)
from yieldfield.api.errors.handlers import register_error_handlers
from yieldfield.application.errors import EntityNotFoundError
from yieldfield.domain.shared.errors import InvalidFindingTransitionError
from yieldfield.infrastructure.connectors.base.connector import ConnectorAuthError

_CASES = [
    (UnauthorizedError("Missing or invalid bearer token."), 401, "unauthorized"),
    (IngestionDisabledError("Ingestion is disabled."), 403, "ingestion_disabled"),
    (InvalidWebhookSignatureError("Bad signature."), 400, "invalid_webhook_signature"),
    (EntityNotFoundError("Finding 'f_1' not found."), 404, "not_found"),
    (InvalidFindingTransitionError("Cannot move."), 409, "invalid_finding_transition"),
    (ConnectorAuthError("Missing required credential: 'api_key'."), 400, "connector_auth_error"),
    (WebhookPayloadTooLargeError("Payload exceeds cap."), 413, "payload_too_large"),
    (InvalidCursorError("Invalid pagination cursor."), 400, "invalid_cursor"),
]


def _app_raising(exc: Exception) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise exc

    return app


@pytest.mark.parametrize(("exc", "status", "code"), _CASES, ids=[c[2] for c in _CASES])
def test_typed_errors_map_to_envelope(exc: Exception, status: int, code: str) -> None:
    client = TestClient(_app_raising(exc), raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["message"] == str(exc)


def test_unhandled_exceptions_become_internal_error_envelope() -> None:
    client = TestClient(_app_raising(ValueError("secret detail")), raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    # Internal details never leak to the client (§11).
    assert "secret detail" not in body["error"]["message"]
