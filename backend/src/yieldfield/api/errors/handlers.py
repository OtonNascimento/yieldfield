"""The standard error envelope and exception handlers (§10).

Every error response the API emits has the shape `{ error: { code, message, details } }`
so the typed frontend client has one predictable failure contract. This module wires
that envelope for FastAPI's `HTTPException` and request-validation failures. Domain and
application error types map onto it as those layers land (Slice 1/3).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from yieldfield.api.errors.exceptions import (
    IngestionDisabledError,
    InvalidWebhookSignatureError,
    UnauthorizedError,
)
from yieldfield.application.errors import EntityNotFoundError
from yieldfield.domain.shared.errors import InvalidFindingTransitionError

# The one sanctioned infrastructure TYPE import outside dependencies/: the spec's §5.4
# mapping table names ConnectorAuthError, so the handler must reference the class. No
# composition happens here.
from yieldfield.infrastructure.connectors.base.connector import ConnectorAuthError


class ErrorBody(BaseModel):
    """The inner error object of the envelope (§10)."""

    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorEnvelope(BaseModel):
    """The standard error response: `{ error: { code, message, details } }`."""

    error: ErrorBody


def _envelope(
    *, code: str, message: str, status_code: int, details: list[dict[str, Any]] | None = None
) -> JSONResponse:
    payload = ErrorEnvelope(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def _http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    # Starlette types handlers against the base Exception; narrow back here.
    http_exc = cast(StarletteHTTPException, exc)
    return _envelope(
        code=f"http_{http_exc.status_code}",
        message=str(http_exc.detail),
        status_code=http_exc.status_code,
    )


async def _validation_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    validation_exc = cast(RequestValidationError, exc)
    return _envelope(
        code="validation_error",
        message="Request validation failed.",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        # type/loc/msg only — the raw errors() echo the submitted `input`, and a
        # type-invalid secret value must never round-trip in a response body (§11).
        details=[
            {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
            for error in validation_exc.errors()
        ],
    )


# Typed exception → (status, code) map (spec §5.4). Message = str(exc): every mapped error
# type carries operator-safe messages (ids/keys only — never secrets, §11).
_TYPED_ERRORS: list[tuple[type[Exception], int, str]] = [
    (UnauthorizedError, status.HTTP_401_UNAUTHORIZED, "unauthorized"),
    (IngestionDisabledError, status.HTTP_403_FORBIDDEN, "ingestion_disabled"),
    (InvalidWebhookSignatureError, status.HTTP_400_BAD_REQUEST, "invalid_webhook_signature"),
    (EntityNotFoundError, status.HTTP_404_NOT_FOUND, "not_found"),
    (InvalidFindingTransitionError, status.HTTP_409_CONFLICT, "invalid_finding_transition"),
    (ConnectorAuthError, status.HTTP_400_BAD_REQUEST, "connector_auth_error"),
]


def _typed_handler(
    status_code: int, code: str
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return _envelope(code=code, message=str(exc), status_code=status_code)

    return handler


async def _unhandled_exception_handler(_: Request, _exc: Exception) -> JSONResponse:
    # Catch-all: every error response is enveloped (§10) and internals never leak (§11).
    return _envelope(
        code="internal_error",
        message="Internal server error.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach the envelope handlers to the app (called from the app factory)."""
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    for exc_type, status_code, code in _TYPED_ERRORS:
        app.add_exception_handler(exc_type, _typed_handler(status_code, code))
    app.add_exception_handler(Exception, _unhandled_exception_handler)
