"""The standard error envelope and exception handlers (§10).

Every error response the API emits has the shape `{ error: { code, message, details } }`
so the typed frontend client has one predictable failure contract. This module wires
that envelope for FastAPI's `HTTPException` and request-validation failures. Domain and
application error types map onto it as those layers land (Slice 1/3).
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


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
        details=[dict(error) for error in validation_exc.errors()],
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach the envelope handlers to the app (called from the app factory)."""
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
