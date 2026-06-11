"""FastAPI application factory — the thin HTTP adapter's entrypoint (§10).

Holds no business logic: it wires settings, logging, CORS, the error envelope, and
the versioned routers, then hands off. Run with `uvicorn yieldfield.api.main:app`.
The OpenAPI schema this app produces becomes the shared contract emitted to
`contracts/` in Slice 3 (§10).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from yieldfield.api.errors.handlers import register_error_handlers
from yieldfield.api.v1.routers import connectors, health, jobs
from yieldfield.config.logging import configure_logging, get_logger
from yieldfield.config.settings import Settings, get_settings

API_V1_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. Settings are validated here, so misconfig fails fast."""
    settings = settings or get_settings()
    configure_logging(settings)
    log = get_logger("yieldfield.api")

    app = FastAPI(
        title="Yieldfield API",
        version="0.0.0",
        debug=settings.debug,
        # Versioned OpenAPI surface (§10).
        openapi_url=f"{API_V1_PREFIX}/openapi.json",
        docs_url=f"{API_V1_PREFIX}/docs",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(health.router, prefix=API_V1_PREFIX)
    app.include_router(jobs.router, prefix=API_V1_PREFIX)
    app.include_router(connectors.router, prefix=API_V1_PREFIX)

    log.info("api.started", environment=settings.environment, version=app.version)
    return app


app = create_app()
