"""Job is a lightweight operational record; its result reference is null-or-both-set (§3, G)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.persistence.errors import PersistenceError
from yieldfield.infrastructure.persistence.job import (
    Job,
    JobResultType,
    JobStatus,
    JobType,
)

_CREATED = datetime(2026, 6, 1, tzinfo=UTC)


def test_pending_job_has_no_result() -> None:
    job = Job(
        id="job_1",
        tenant_id=TenantId("tenant-1"),
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.PENDING,
        created_at=_CREATED,
    )
    assert job.status is JobStatus.PENDING
    assert job.result_type is None
    assert job.result_ref is None


def test_result_type_without_ref_raises() -> None:
    with pytest.raises(PersistenceError):
        Job(
            id="job_1",
            tenant_id=TenantId("tenant-1"),
            job_type=JobType.RUN_RECONCILIATION,
            status=JobStatus.SUCCEEDED,
            created_at=_CREATED,
            result_type=JobResultType.RECONCILIATION,
        )


def test_result_ref_without_type_raises() -> None:
    with pytest.raises(PersistenceError):
        Job(
            id="job_1",
            tenant_id=TenantId("tenant-1"),
            job_type=JobType.RUN_RECONCILIATION,
            status=JobStatus.SUCCEEDED,
            created_at=_CREATED,
            result_ref="rec_1",
        )


def test_succeeded_job_with_result_pair_is_valid() -> None:
    job = Job(
        id="job_1",
        tenant_id=TenantId("tenant-1"),
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.SUCCEEDED,
        created_at=_CREATED,
        result_type=JobResultType.RECONCILIATION,
        result_ref="rec_1",
    )
    assert job.result_type is JobResultType.RECONCILIATION
    assert job.result_ref == "rec_1"
