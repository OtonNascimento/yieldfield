"""POST/GET /reconciliations (spec §5.2): trigger a run (202 + job handle) and read the
append-only financial audit trail (decision C).

The API pre-generates `reconciliation_id` and passes it with the job, so a Celery
redelivery/retry converges on the same run while a fresh POST is a new historical record
(decision C/E). Reads are newest-first; each run is immutable.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, status

from yieldfield.api.v1.dependencies.auth import CurrentTenant
from yieldfield.api.v1.dependencies.pagination import PageParamsDep, paginate
from yieldfield.api.v1.dependencies.services import (
    RUN_RECONCILIATION_TASK,
    JobSubmitterDep,
    ReconciliationRepo,
)
from yieldfield.api.v1.schemas.common import JobAccepted, PageMeta
from yieldfield.api.v1.schemas.reconciliations import (
    ReconciliationCreate,
    ReconciliationPage,
    ReconciliationRead,
)
from yieldfield.application.errors import EntityNotFoundError
from yieldfield.domain.shared.ids import ReconciliationId

router = APIRouter(prefix="/reconciliations", tags=["reconciliations"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run reconciliation for a window",
    response_model=JobAccepted,
)
def run_reconciliation(
    body: ReconciliationCreate, tenant_id: CurrentTenant, submitter: JobSubmitterDep
) -> JobAccepted:
    reconciliation_id = f"rec_{uuid4()}"
    job_id = submitter.submit(
        tenant_id,
        RUN_RECONCILIATION_TASK,
        body.window.start.isoformat(),
        body.window.end.isoformat(),
        reconciliation_id,
    )
    return JobAccepted(job_id=job_id)


@router.get(
    "/{reconciliation_id}",
    summary="Read one reconciliation run",
    response_model=ReconciliationRead,
)
def get_reconciliation(
    reconciliation_id: str, tenant_id: CurrentTenant, reconciliations: ReconciliationRepo
) -> ReconciliationRead:
    reconciliation = reconciliations.get(tenant_id, ReconciliationId(reconciliation_id))
    if reconciliation is None:
        raise EntityNotFoundError(f"Reconciliation {reconciliation_id!r} not found.")
    return ReconciliationRead.from_reconciliation(reconciliation)


@router.get(
    "", summary="List reconciliation runs (newest first)", response_model=ReconciliationPage
)
def list_reconciliations(
    tenant_id: CurrentTenant, reconciliations: ReconciliationRepo, page: PageParamsDep
) -> ReconciliationPage:
    ordered = sorted(
        reconciliations.list_for_tenant(tenant_id), key=lambda r: r.executed_at, reverse=True
    )
    items, next_cursor = paginate(ordered, page)
    return ReconciliationPage(
        items=[ReconciliationRead.from_reconciliation(r) for r in items],
        meta=PageMeta(next_cursor=next_cursor),
    )
