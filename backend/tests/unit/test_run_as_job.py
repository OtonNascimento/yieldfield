"""run_as_job (spec §3): RUNNING commits first; SUCCEEDED commits WITH the business write;
FAILED rolls business writes back first — no phantom records, durable failures."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.messaging.run_as_job import MessagingError, run_as_job
from yieldfield.infrastructure.persistence.job import Job, JobResultType, JobStatus, JobType

TENANT = TenantId("t_1")
FIXED_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _job(status: JobStatus = JobStatus.PENDING) -> Job:
    return Job(
        id="job_1",
        tenant_id=TENANT,
        job_type=JobType.RUN_RECONCILIATION,
        status=status,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


class FakeLedger:
    def __init__(self, job: Job | None) -> None:
        self._job = job
        self.updates: list[Job] = []

    def get(self, tenant_id: TenantId, job_id: str) -> Job | None:
        return self._job

    def update(self, tenant_id: TenantId, job: Job) -> None:
        self.updates.append(job)


class Tx:
    def __init__(self) -> None:
        self.events: list[str] = []

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


def test_success_with_result_pair_commits_running_then_succeeded() -> None:
    ledger, tx = FakeLedger(_job()), Tx()
    run_as_job(
        jobs=ledger,
        commit=tx.commit,
        rollback=tx.rollback,
        tenant_id=TENANT,
        job_id="job_1",
        work=lambda: (JobResultType.RECONCILIATION, "rec_1"),
        clock=lambda: FIXED_NOW,
        celery_task_id="celery-1",
    )
    running, succeeded = ledger.updates
    assert running.status is JobStatus.RUNNING
    assert running.started_at == FIXED_NOW
    assert running.celery_task_id == "celery-1"
    assert succeeded.status is JobStatus.SUCCEEDED
    assert succeeded.finished_at == FIXED_NOW
    assert succeeded.result_type is JobResultType.RECONCILIATION
    assert succeeded.result_ref == "rec_1"
    assert tx.events == ["commit", "commit"]  # RUNNING txn, then business+SUCCEEDED txn


def test_success_with_no_result_leaves_the_pair_null() -> None:
    ledger, tx = FakeLedger(_job()), Tx()
    run_as_job(
        jobs=ledger,
        commit=tx.commit,
        rollback=tx.rollback,
        tenant_id=TENANT,
        job_id="job_1",
        work=lambda: None,
        clock=lambda: FIXED_NOW,
    )
    assert ledger.updates[-1].status is JobStatus.SUCCEEDED
    assert ledger.updates[-1].result_type is None
    assert ledger.updates[-1].result_ref is None


def test_failure_rolls_back_business_writes_then_records_failed_and_reraises() -> None:
    ledger, tx = FakeLedger(_job()), Tx()

    def explode() -> None:
        raise RuntimeError("connector timed out")

    with pytest.raises(RuntimeError, match="connector timed out"):
        run_as_job(
            jobs=ledger,
            commit=tx.commit,
            rollback=tx.rollback,
            tenant_id=TENANT,
            job_id="job_1",
            work=explode,
            clock=lambda: FIXED_NOW,
        )
    failed = ledger.updates[-1]
    assert failed.status is JobStatus.FAILED
    assert failed.error == "connector timed out"
    assert failed.finished_at == FIXED_NOW
    assert failed.result_type is None  # no phantom result on failure (§3)
    # Business writes are discarded BEFORE the FAILED status is committed.
    assert tx.events == ["commit", "rollback", "commit"]


def test_missing_job_raises_messaging_error() -> None:
    with pytest.raises(MessagingError, match="job_1"):
        run_as_job(
            jobs=FakeLedger(None),
            commit=lambda: None,
            rollback=lambda: None,
            tenant_id=TENANT,
            job_id="job_1",
            work=lambda: None,
        )


@pytest.mark.parametrize("status", [JobStatus.SUCCEEDED, JobStatus.FAILED])
def test_redelivery_of_a_finished_job_is_a_noop(status: JobStatus) -> None:
    # acks_late redelivery converges: a terminal job is never re-run (§3/§8).
    ledger, tx = FakeLedger(_job(status)), Tx()
    calls: list[str] = []
    run_as_job(
        jobs=ledger,
        commit=tx.commit,
        rollback=tx.rollback,
        tenant_id=TENANT,
        job_id="job_1",
        work=lambda: calls.append("ran"),
    )
    assert calls == []
    assert ledger.updates == []
    assert tx.events == []
