"""Connector + Job repositories round-trip against Postgres and stay tenant-isolated (§11)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
from yieldfield.domain.billing.tenant import Tenant
from yieldfield.domain.shared.ids import ConnectorId, TenantId
from yieldfield.infrastructure.persistence.job import (
    Job,
    JobResultType,
    JobStatus,
    JobType,
)
from yieldfield.infrastructure.persistence.repositories import (
    SqlAlchemyConnectorRepository,
    SqlAlchemyJobRepository,
    SqlAlchemyTenantRepository,
)

pytestmark = pytest.mark.integration


def test_connector_round_trip_and_find_by_id(session: Session) -> None:
    tid = TenantId("tenant-con")
    SqlAlchemyTenantRepository(session).add(Tenant(id=tid, name="Con"))
    session.flush()
    repo = SqlAlchemyConnectorRepository(session)
    connector = Connector(
        id=ConnectorId("con_1"),
        tenant_id=tid,
        connector_type=ConnectorType.STRIPE_BILLING,
        status=ConnectorStatus.ACTIVE,
    )
    repo.add(tid, connector, b"ENCRYPTED-BLOB")
    session.flush()

    assert repo.get(tid, ConnectorId("con_1")) == connector
    assert repo.load_credentials(tid, ConnectorId("con_1")) == b"ENCRYPTED-BLOB"
    assert repo.list_for_tenant(tid) == [connector]
    # find_by_id resolves the owning tenant from the id alone (webhook ingress, §6).
    assert repo.find_by_id(ConnectorId("con_1")) == connector


def test_connector_reads_are_tenant_isolated(session: Session) -> None:
    tenants = SqlAlchemyTenantRepository(session)
    tenants.add(Tenant(id=TenantId("t_A"), name="A"))
    tenants.add(Tenant(id=TenantId("t_B"), name="B"))
    session.flush()
    repo = SqlAlchemyConnectorRepository(session)
    repo.add(
        TenantId("t_A"),
        Connector(
            id=ConnectorId("con_A"),
            tenant_id=TenantId("t_A"),
            connector_type=ConnectorType.STRIPE_BILLING,
        ),
        b"A-BLOB",
    )
    session.flush()
    assert repo.get(TenantId("t_B"), ConnectorId("con_A")) is None
    assert repo.list_for_tenant(TenantId("t_B")) == []
    # Positive leg: the owning tenant can still read its own connector.
    assert repo.get(TenantId("t_A"), ConnectorId("con_A")) is not None


def test_job_lifecycle_round_trip(session: Session) -> None:
    tid = TenantId("tenant-job")
    SqlAlchemyTenantRepository(session).add(Tenant(id=tid, name="Job"))
    session.flush()
    repo = SqlAlchemyJobRepository(session)
    job = Job(
        id="job_1",
        tenant_id=tid,
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.PENDING,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    repo.add(tid, job)
    session.flush()

    succeeded = Job(
        id="job_1",
        tenant_id=tid,
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.SUCCEEDED,
        created_at=job.created_at,
        started_at=datetime(2026, 6, 1, 0, 0, 1, tzinfo=UTC),
        finished_at=datetime(2026, 6, 1, 0, 0, 2, tzinfo=UTC),
        result_type=JobResultType.RECONCILIATION,
        result_ref="rec_1",
    )
    repo.update(tid, succeeded)
    session.flush()

    reloaded = repo.get(tid, "job_1")
    assert reloaded is not None
    assert reloaded.status is JobStatus.SUCCEEDED
    assert reloaded.result_type is JobResultType.RECONCILIATION
    assert reloaded.result_ref == "rec_1"
    # Lifecycle timestamps round-trip (tz-aware) through the update path.
    assert reloaded.started_at == datetime(2026, 6, 1, 0, 0, 1, tzinfo=UTC)
    assert reloaded.finished_at == datetime(2026, 6, 1, 0, 0, 2, tzinfo=UTC)

    # Tenant isolation: another tenant cannot read this job.
    assert repo.get(TenantId("other"), "job_1") is None


def test_stale_pending_sweep_read_filters_status_and_age(session: Session) -> None:
    tid = TenantId("tenant-sweep")
    SqlAlchemyTenantRepository(session).add(Tenant(id=tid, name="Sweep"))
    session.flush()
    repo = SqlAlchemyJobRepository(session)

    def _job(job_id: str, status: JobStatus, created_at: datetime) -> Job:
        return Job(
            id=job_id,
            tenant_id=tid,
            job_type=JobType.INGEST_INVOICES,
            status=status,
            created_at=created_at,
        )

    repo.add(tid, _job("job_stale", JobStatus.PENDING, datetime(2026, 6, 1, tzinfo=UTC)))
    repo.add(tid, _job("job_fresh", JobStatus.PENDING, datetime(2026, 6, 3, tzinfo=UTC)))
    repo.add(tid, _job("job_running", JobStatus.RUNNING, datetime(2026, 6, 1, tzinfo=UTC)))
    session.flush()

    stale = repo.list_stale_pending(datetime(2026, 6, 2, tzinfo=UTC))
    assert [j.id for j in stale] == ["job_stale"]  # PENDING and older than the cutoff only
