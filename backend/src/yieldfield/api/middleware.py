"""Request-scoped log context (§11 observability, audit PR-4a).

Every request gets a correlation id (inbound `X-Request-ID` or a fresh uuid4) bound into
structlog's contextvars, so every log line emitted while handling it — router, use-case,
adapter — carries the id. The id is echoed on the response, and one `http.request` line
records method/path/status/duration per request.

Deliberately a pure ASGI middleware (not `BaseHTTPMiddleware`): the downstream app runs
in the SAME context, so contextvars bound inside the request — the auth dependency binds
`tenant_id` (§11) — are still visible when the final log line is emitted here.
"""

from __future__ import annotations

import time
from uuid import uuid4

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from yieldfield.config.logging import get_logger

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get(REQUEST_ID_HEADER) or str(uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status: dict[str, int | None] = {"code": None}

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        started = time.perf_counter()
        try:
            await self._app(scope, receive, send_with_request_id)
        finally:
            get_logger("yieldfield.api").info(
                "http.request",
                method=scope["method"],
                path=scope["path"],
                status=status["code"],
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
