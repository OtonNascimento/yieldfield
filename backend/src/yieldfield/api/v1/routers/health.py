"""Health/readiness endpoints — the only routes Slice 0 exposes (§10).

Liveness needs no I/O. Readiness will, in later slices, check the datastores and
broker; for Slice 0 it reports the same shallow status so orchestration probes have
a stable contract to call. No business logic lives here.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from yieldfield.config.settings import get_settings

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    """Shallow liveness/readiness payload."""

    status: str
    service: str
    environment: str


@router.get("/health", summary="Liveness probe")
def health() -> HealthStatus:
    settings = get_settings()
    return HealthStatus(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
    )


@router.get("/ready", summary="Readiness probe")
def ready() -> HealthStatus:
    # Slice 2+ extends this to verify Postgres/ClickHouse/Redis connectivity.
    settings = get_settings()
    return HealthStatus(
        status="ready",
        service=settings.app_name,
        environment=settings.environment,
    )
