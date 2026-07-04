"""The worker registers tasks under exactly the names the API enqueues (spec §7),
and its composition roots enforce the flag gate and tenant scoping (audit TE-3, TE-4)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def test_money_path_tasks_are_registered_under_the_api_contract_names() -> None:
    import yieldfield.workers.tasks  # noqa: F401 — importing registers the tasks
    from yieldfield.api.v1.dependencies.services import (
        INGEST_INVOICES_TASK,
        INGEST_USAGE_EVENTS_TASK,
        RUN_RECONCILIATION_TASK,
    )
    from yieldfield.workers.celery_app import celery_app

    registered = set(celery_app.tasks)
    assert {INGEST_INVOICES_TASK, INGEST_USAGE_EVENTS_TASK, RUN_RECONCILIATION_TASK} <= registered


def test_worker_boot_registers_tasks_without_manual_imports() -> None:
    # `celery -A yieldfield.workers.celery_app worker` imports only celery_app; without
    # `include` a real worker registers NO money-path tasks and every enqueue sits
    # PENDING forever — tests importing tasks explicitly had hidden this (audit WK-2).
    from yieldfield.workers.celery_app import celery_app

    assert "yieldfield.workers.tasks" in celery_app.conf.include


def test_beat_schedule_sweeps_stale_jobs_with_a_registered_task() -> None:
    import yieldfield.workers.tasks  # noqa: F401 — importing registers the tasks
    from yieldfield.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["sweep-stale-jobs"]
    assert entry["task"] == "yieldfield.sweep_stale_jobs"
    assert entry["task"] in celery_app.tasks  # the schedule points at a real task


def test_job_type_map_covers_exactly_the_exported_task_names() -> None:
    # A task name the API enqueues but this map misses KeyErrors at submit time (500);
    # exact coverage forces the map update alongside any new task constant (audit TE-4).
    from yieldfield.api.v1.dependencies.services import (
        _JOB_TYPE_BY_TASK,
        INGEST_INVOICES_TASK,
        INGEST_USAGE_EVENTS_TASK,
        RUN_RECONCILIATION_TASK,
    )

    assert set(_JOB_TYPE_BY_TASK) == {
        INGEST_INVOICES_TASK,
        INGEST_USAGE_EVENTS_TASK,
        RUN_RECONCILIATION_TASK,
    }


# --- Task-body composition guards (audit TE-3) -------------------------------------
# These drive the REAL task bodies over an in-memory SQLite ledger: only
# `_session_factory` and `get_settings` are swapped, so the composition inside
# workers/tasks.py (flag gate, tenant-scoped registration, run_as_job wiring) is
# exactly what runs.

_START = "2026-01-01T00:00:00+00:00"
_END = "2026-02-01T00:00:00+00:00"


def _sqlite_sessions() -> sessionmaker[Session]:
    from yieldfield.infrastructure.persistence.engine import build_sessionmaker
    from yieldfield.infrastructure.persistence.models import Base

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    # Only the tables the ingestion task touches; FindingRow's pg ARRAY can't build here.
    tables = [Base.metadata.tables[name] for name in ("tenants", "connectors", "jobs")]
    Base.metadata.create_all(engine, tables=tables)
    return build_sessionmaker(engine)


def _seed_pending_job(
    factory: sessionmaker[Session], *, tenant_ids: tuple[str, ...], job_id: str
) -> None:
    from yieldfield.domain.shared.ids import TenantId
    from yieldfield.infrastructure.persistence.job import Job, JobStatus, JobType
    from yieldfield.infrastructure.persistence.models import TenantRow
    from yieldfield.infrastructure.persistence.repositories import SqlAlchemyJobRepository

    with factory() as session:
        for tenant_id in tenant_ids:
            session.add(TenantRow(id=tenant_id, name=tenant_id))
        SqlAlchemyJobRepository(session).add(
            TenantId(tenant_ids[0]),
            Job(
                id=job_id,
                tenant_id=TenantId(tenant_ids[0]),
                job_type=JobType.INGEST_INVOICES,
                status=JobStatus.PENDING,
                created_at=datetime.now(UTC),
            ),
        )
        session.commit()


def _job_status_and_error(
    factory: sessionmaker[Session], tenant_id: str, job_id: str
) -> tuple[object, str]:
    from yieldfield.domain.shared.ids import TenantId
    from yieldfield.infrastructure.persistence.repositories import SqlAlchemyJobRepository

    with factory() as session:
        job = SqlAlchemyJobRepository(session).get(TenantId(tenant_id), job_id)
    assert job is not None
    return job.status, job.error or ""


def test_ingest_invoices_fails_the_job_when_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Defense in depth behind the API gate (§16): the worker re-checks the flag and
    # fails the Job durably instead of silently pulling (audit TE-3).
    import yieldfield.workers.tasks as tasks
    from yieldfield.config.settings import Settings
    from yieldfield.infrastructure.persistence.job import JobStatus

    factory = _sqlite_sessions()
    _seed_pending_job(factory, tenant_ids=("tenant-a",), job_id="job-1")
    settings = Settings(_env_file=None, ingestion_enabled=False)
    monkeypatch.setattr(tasks, "_session_factory", lambda: factory)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="YIELDFIELD_INGESTION_ENABLED"):
        tasks.ingest_invoices_task("job-1", "tenant-a", _START, _END, "conn-1")

    status, error = _job_status_and_error(factory, "tenant-a", "job-1")
    assert status is JobStatus.FAILED
    assert "YIELDFIELD_INGESTION_ENABLED" in error


def test_ingest_invoices_fails_when_the_connector_belongs_to_another_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # build_authenticated is tenant-scoped: another tenant's connector id is "not
    # found" — the credentials are never read across the boundary (audit TE-3, §11).
    from cryptography.fernet import Fernet

    import yieldfield.workers.tasks as tasks
    from yieldfield.config.settings import Settings
    from yieldfield.infrastructure.connectors.base.connector import ConnectorError
    from yieldfield.infrastructure.persistence.job import JobStatus
    from yieldfield.infrastructure.persistence.models import ConnectorRow

    factory = _sqlite_sessions()
    _seed_pending_job(factory, tenant_ids=("tenant-a", "tenant-b"), job_id="job-1")
    with factory() as session:
        session.add(
            ConnectorRow(
                id="conn-b",
                tenant_id="tenant-b",
                connector_type="stripe_billing",
                status="active",
                encrypted_credentials=b"opaque",
            )
        )
        session.commit()
    settings = Settings(
        _env_file=None, ingestion_enabled=True, credentials_key=Fernet.generate_key().decode()
    )
    monkeypatch.setattr(tasks, "_session_factory", lambda: factory)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)

    with pytest.raises(ConnectorError, match="not found for tenant"):
        tasks.ingest_invoices_task("job-1", "tenant-a", _START, _END, "conn-b")

    status, error = _job_status_and_error(factory, "tenant-a", "job-1")
    assert status is JobStatus.FAILED
    assert "not found" in error
