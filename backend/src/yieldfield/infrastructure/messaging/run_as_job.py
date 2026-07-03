"""Job-lifecycle wrapper for worker tasks (spec §3, §7) — the operational audit boundary.

Transaction choreography (the load-bearing part):
  txn 1: mark RUNNING (+ started_at, celery_task_id) and COMMIT — pollers see progress.
  txn 2: run `work()`; on success, mark SUCCEEDED (+ result pair) and COMMIT — the business
         write and the success status land atomically.
  on exception: ROLLBACK txn 2 (discarding any partial business writes), then mark FAILED
         (+ error, finished_at) in its own committed txn, and RE-RAISE.
A failed run therefore leaves a durable FAILED Job and no phantom financial record; a
redelivered finished job is a no-op (idempotent convergence, §8). Use-cases stay
job-unaware — only this wrapper and the worker tasks know Jobs exist.

Structured logs at the job boundary (§11): tenant_id/job_id/outcome — never secrets.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from yieldfield.config.logging import get_logger
from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.persistence.job import Job, JobResultType, JobStatus

JobResult = tuple[JobResultType, str]

_TERMINAL = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED})

# A payload that kills the worker outright is redelivered by acks_late and would loop
# forever (audit WK-1). Each delivery counts on the RUNNING transition; at the cap the
# job FAILS durably and the message is consumed.
MAX_DELIVERY_ATTEMPTS = 3


class MessagingError(Exception):
    """A job-orchestration failure (e.g. the Job row is missing)."""


class JobLedger(Protocol):
    """The slice of the job repository this wrapper needs (satisfied by SqlAlchemyJobRepository)."""

    def get(self, tenant_id: TenantId, job_id: str) -> Job | None: ...
    def update(self, tenant_id: TenantId, job: Job) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def run_as_job(
    *,
    jobs: JobLedger,
    commit: Callable[[], None],
    rollback: Callable[[], None],
    tenant_id: TenantId,
    job_id: str,
    work: Callable[[], JobResult | None],
    clock: Callable[[], datetime] = _utcnow,
    celery_task_id: str | None = None,
) -> None:
    log = get_logger("yieldfield.jobs").bind(tenant_id=str(tenant_id), job_id=job_id)
    job = jobs.get(tenant_id, job_id)
    if job is None:
        raise MessagingError(f"Job {job_id!r} not found for tenant {tenant_id!r}.")
    if job.status in _TERMINAL:
        log.info("job.redelivered_noop", status=job.status.value)
        return
    if job.attempts >= MAX_DELIVERY_ATTEMPTS:
        failed = replace(
            job,
            status=JobStatus.FAILED,
            finished_at=clock(),
            error=f"exceeded {MAX_DELIVERY_ATTEMPTS} delivery attempts; "
            f"poison redelivery stopped (§3).",
        )
        jobs.update(tenant_id, failed)
        commit()
        log.error("job.delivery_exhausted", attempts=job.attempts)
        return

    running = replace(
        job,
        status=JobStatus.RUNNING,
        started_at=clock(),
        celery_task_id=celery_task_id,
        attempts=job.attempts + 1,
    )
    jobs.update(tenant_id, running)
    commit()
    log.info("job.started", job_type=job.job_type.value)

    try:
        result = work()
    except Exception as exc:
        rollback()
        failed = replace(running, status=JobStatus.FAILED, finished_at=clock(), error=str(exc))
        jobs.update(tenant_id, failed)
        commit()
        log.error("job.failed", error=str(exc))
        raise

    result_type, result_ref = result if result is not None else (None, None)
    succeeded = replace(
        running,
        status=JobStatus.SUCCEEDED,
        finished_at=clock(),
        result_type=result_type,
        result_ref=result_ref,
    )
    jobs.update(tenant_id, succeeded)
    commit()
    log.info(
        "job.succeeded",
        result_type=result_type.value if result_type is not None else None,
        result_ref=result_ref,
    )
