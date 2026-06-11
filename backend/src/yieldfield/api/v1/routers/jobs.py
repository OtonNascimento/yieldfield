"""GET /jobs/{job_id} (spec §5.2) — the authoritative, OLTP-backed async-status surface (§3).

Thin adapter: resolve tenant, read the Job, serialize. On SUCCEEDED the client follows
`result_ref` (e.g. to GET /reconciliations/{id}); failures surface here as FAILED + error.
"""

from __future__ import annotations

from fastapi import APIRouter

from yieldfield.api.v1.dependencies.auth import CurrentTenant
from yieldfield.api.v1.dependencies.services import JobRepo, job_status_read
from yieldfield.api.v1.schemas.jobs import JobStatusRead
from yieldfield.application.errors import EntityNotFoundError

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", summary="Poll an async job", response_model=JobStatusRead)
def get_job(job_id: str, tenant_id: CurrentTenant, jobs: JobRepo) -> JobStatusRead:
    job = jobs.get(tenant_id, job_id)
    if job is None:
        raise EntityNotFoundError(f"Job {job_id!r} not found.")
    return job_status_read(job)
