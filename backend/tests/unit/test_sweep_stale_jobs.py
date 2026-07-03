"""Stale-PENDING sweep (§3, audit WK-2): enqueue-failed jobs get a durable FAILED outcome."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.messaging.sweep import sweep_stale_pending
from yieldfield.infrastructure.persistence.job import Job, JobStatus, JobType

FIXED_NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def _job(job_id: str, tenant: str, status: JobStatus, age: timedelta) -> Job:
    return Job(
        id=job_id,
        tenant_id=TenantId(tenant),
        job_type=JobType.INGEST_INVOICES,
        status=status,
        created_at=FIXED_NOW - age,
    )


class FakeLedger:
    """Filters like the real repository: PENDING and older than the cutoff."""

    def __init__(self, jobs: list[Job]) -> None:
        self._jobs = jobs
        self.updates: list[tuple[TenantId, Job]] = []

    def list_stale_pending(self, cutoff: datetime) -> list[Job]:
        return [j for j in self._jobs if j.status is JobStatus.PENDING and j.created_at < cutoff]

    def update(self, tenant_id: TenantId, job: Job) -> None:
        self.updates.append((tenant_id, job))


class Tx:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def test_stale_pending_jobs_fail_with_a_durable_reason() -> None:
    ledger = FakeLedger([_job("job_old", "t1", JobStatus.PENDING, timedelta(hours=7))])
    tx = Tx()
    swept = sweep_stale_pending(
        jobs=ledger, commit=tx.commit, older_than=timedelta(hours=6), clock=lambda: FIXED_NOW
    )
    assert swept == 1
    tenant, failed = ledger.updates[0]
    assert tenant == TenantId("t1")  # update scoped to the job's own tenant
    assert failed.status is JobStatus.FAILED
    assert failed.finished_at == FIXED_NOW
    assert failed.error is not None and "stale" in failed.error
    assert tx.commits == 1


def test_fresh_pending_and_running_jobs_are_untouched() -> None:
    ledger = FakeLedger(
        [
            _job("job_fresh", "t1", JobStatus.PENDING, timedelta(minutes=5)),
            _job("job_running", "t1", JobStatus.RUNNING, timedelta(hours=48)),
        ]
    )
    tx = Tx()
    swept = sweep_stale_pending(
        jobs=ledger, commit=tx.commit, older_than=timedelta(hours=6), clock=lambda: FIXED_NOW
    )
    assert swept == 0
    assert ledger.updates == []
    assert tx.commits == 0  # an empty sweep writes nothing


def test_sweep_spans_tenants_but_updates_stay_tenant_scoped() -> None:
    ledger = FakeLedger(
        [
            _job("job_a", "tenant-a", JobStatus.PENDING, timedelta(hours=10)),
            _job("job_b", "tenant-b", JobStatus.PENDING, timedelta(hours=10)),
        ]
    )
    tx = Tx()
    swept = sweep_stale_pending(
        jobs=ledger, commit=tx.commit, older_than=timedelta(hours=6), clock=lambda: FIXED_NOW
    )
    assert swept == 2
    assert [(str(t), j.id) for t, j in ledger.updates] == [
        ("tenant-a", "job_a"),
        ("tenant-b", "job_b"),
    ]
    assert tx.commits == 1
