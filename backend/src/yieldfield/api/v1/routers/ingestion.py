"""POST /ingestion/{invoices,usage-events} → 202 (spec §5.2).

Risky live pulls sit behind `ingestion_enabled` (§16) → 403 `ingestion_disabled` when off.
Each trigger persists a PENDING Job and enqueues the matching worker task; connector
failures surface later as a FAILED Job via GET /jobs/{id}, not as an HTTP error here.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from yieldfield.api.errors.exceptions import IngestionDisabledError
from yieldfield.api.v1.dependencies.auth import CurrentTenant
from yieldfield.api.v1.dependencies.services import (
    INGEST_INVOICES_TASK,
    INGEST_USAGE_EVENTS_TASK,
    JobSubmitterDep,
)
from yieldfield.api.v1.dependencies.settings import SettingsDep
from yieldfield.api.v1.schemas.common import JobAccepted
from yieldfield.api.v1.schemas.ingestion import IngestionRequest
from yieldfield.config.settings import Settings

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


def _require_enabled(settings: Settings) -> None:
    if not settings.ingestion_enabled:
        raise IngestionDisabledError(
            "Ingestion is disabled (set YIELDFIELD_INGESTION_ENABLED to enable live pulls)."
        )


def _submit(
    submitter: JobSubmitterDep, tenant_id: CurrentTenant, task_name: str, body: IngestionRequest
) -> JobAccepted:
    job_id = submitter.submit(
        tenant_id,
        task_name,
        body.window.start.isoformat(),
        body.window.end.isoformat(),
        body.connector_id,
    )
    return JobAccepted(job_id=job_id)


@router.post(
    "/invoices",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger invoice ingestion",
    response_model=JobAccepted,
)
def ingest_invoices(
    body: IngestionRequest,
    tenant_id: CurrentTenant,
    settings: SettingsDep,
    submitter: JobSubmitterDep,
) -> JobAccepted:
    _require_enabled(settings)
    return _submit(submitter, tenant_id, INGEST_INVOICES_TASK, body)


@router.post(
    "/usage-events",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger usage-event ingestion",
    response_model=JobAccepted,
)
def ingest_usage_events(
    body: IngestionRequest,
    tenant_id: CurrentTenant,
    settings: SettingsDep,
    submitter: JobSubmitterDep,
) -> JobAccepted:
    _require_enabled(settings)
    return _submit(submitter, tenant_id, INGEST_USAGE_EVENTS_TASK, body)
