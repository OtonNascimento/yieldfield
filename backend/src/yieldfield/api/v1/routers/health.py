"""Health/readiness endpoints (§10, §11).

Liveness needs no I/O. Readiness probes the configured datastores/broker via
`dependencies/readiness.py` and degrades to 503 when any configured dependency fails —
orchestration probes get a truthful answer, and the checks themselves never raise.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from yieldfield.api.v1.dependencies import readiness
from yieldfield.api.v1.dependencies.settings import SettingsDep
from yieldfield.config.settings import get_settings

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    """Shallow liveness payload."""

    status: str
    service: str
    environment: str


class ReadyStatus(BaseModel):
    """Readiness payload: overall status + per-dependency connectivity (§11)."""

    status: str
    service: str
    environment: str
    checks: dict[str, str]


@router.get("/health", summary="Liveness probe")
def health() -> HealthStatus:
    settings = get_settings()
    return HealthStatus(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
    )


@router.get("/ready", summary="Readiness probe", response_model=ReadyStatus)
def ready(response: Response, settings: SettingsDep) -> ReadyStatus:
    checks = readiness.dependency_checks(settings)
    degraded = "error" in checks.values()
    if degraded:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyStatus(
        status="degraded" if degraded else "ready",
        service=settings.app_name,
        environment=settings.environment,
        checks=checks,
    )
