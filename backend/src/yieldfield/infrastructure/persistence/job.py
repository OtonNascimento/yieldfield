"""The Job operational record (§3) — execution lifecycle, distinct from the financial
Reconciliation record. Infrastructure-only: the pure domain and the application use-cases
never see it. The result reference is a generic (result_type, result_ref) pair so future
job types reference different artifacts with no schema change (spec decision G).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.persistence.errors import PersistenceError


class JobType(StrEnum):
    RUN_RECONCILIATION = "run_reconciliation"
    INGEST_INVOICES = "ingest_invoices"
    INGEST_USAGE_EVENTS = "ingest_usage_events"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobResultType(StrEnum):
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    tenant_id: TenantId
    job_type: JobType
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result_type: JobResultType | None = None
    result_ref: str | None = None
    celery_task_id: str | None = None

    def __post_init__(self) -> None:
        if (self.result_type is None) != (self.result_ref is None):
            raise PersistenceError(
                "Job result_type and result_ref must be set together (spec decision G)."
            )
