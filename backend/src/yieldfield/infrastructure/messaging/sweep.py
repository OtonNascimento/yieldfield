"""Stale-PENDING sweep (§3, audit WK-2).

`JobSubmitter` commits the PENDING row BEFORE enqueueing (§3); if the enqueue then
fails, the row stays durably PENDING with no worker behind it and clients poll forever.
The sweep gives such rows a visible, durable outcome: FAILED with a reason, after a
configurable timeout. Scheduled via Celery beat (worker `-B` in the compose stack).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from yieldfield.config.logging import get_logger
from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.persistence.job import Job, JobStatus


class StaleJobLedger(Protocol):
    """The repository slice the sweeper needs (satisfied by SqlAlchemyJobRepository)."""

    def list_stale_pending(self, cutoff: datetime) -> Sequence[Job]: ...
    def update(self, tenant_id: TenantId, job: Job) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def sweep_stale_pending(
    *,
    jobs: StaleJobLedger,
    commit: Callable[[], None],
    older_than: timedelta,
    clock: Callable[[], datetime] = _utcnow,
) -> int:
    """Mark PENDING jobs older than `older_than` FAILED; return how many were swept."""
    log = get_logger("yieldfield.jobs")
    now = clock()
    stale = list(jobs.list_stale_pending(now - older_than))
    for job in stale:
        failed = replace(
            job,
            status=JobStatus.FAILED,
            finished_at=now,
            error=f"stale: still PENDING after {older_than}; the enqueue likely failed (§3).",
        )
        jobs.update(job.tenant_id, failed)
        log.warning("job.swept_stale", tenant_id=str(job.tenant_id), job_id=job.id)
    if stale:
        commit()
    return len(stale)
