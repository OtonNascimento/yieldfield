"""Celery tasks for the money path (spec §7) — one composition root per task.

Args are plain strings (job_id, tenant_id, *task_args) so payloads stay JSON-serializable;
windows travel as ISO-8601 with offsets. The engine and ClickHouse client are built once
per worker process (lru_cache); each task run owns one Session and its transactions via
`run_as_job`. Ingestion tasks re-check the `ingestion_enabled` flag (defense in depth
behind the API gate, §16): when off they fail the Job rather than silently pulling.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from yieldfield.application.ingestion.ingest_invoices import IngestInvoices
from yieldfield.application.ingestion.ingest_usage_events import IngestUsageEvents
from yieldfield.application.reconciliation.run_reconciliation import RunReconciliation
from yieldfield.config.logging import get_logger
from yieldfield.config.settings import get_settings
from yieldfield.domain.shared.ids import ConnectorId, ReconciliationId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.analytics_store.clickhouse_client import create_clickhouse_client
from yieldfield.infrastructure.analytics_store.clickhouse_usage_event_store import (
    ClickHouseUsageEventStore,
)
from yieldfield.infrastructure.connectors.registration import ConnectorRegistrationService
from yieldfield.infrastructure.messaging.run_as_job import JobResult, run_as_job
from yieldfield.infrastructure.persistence.engine import build_sessionmaker, create_db_engine
from yieldfield.infrastructure.persistence.job import JobResultType
from yieldfield.infrastructure.persistence.repositories import (
    SqlAlchemyConnectorRepository,
    SqlAlchemyContractRepository,
    SqlAlchemyInvoiceRepository,
    SqlAlchemyJobRepository,
    SqlAlchemyPlanRepository,
    SqlAlchemyReconciliationRepository,
)
from yieldfield.infrastructure.security.credential_cipher import (
    CredentialCipherError,
    FernetCredentialCipher,
)
from yieldfield.workers.celery_app import celery_app

_log = get_logger("yieldfield.workers")


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return build_sessionmaker(create_db_engine(get_settings().database_url))


@lru_cache(maxsize=1)
def _usage_event_store() -> ClickHouseUsageEventStore:
    return ClickHouseUsageEventStore(create_clickhouse_client(get_settings().clickhouse_url))


def _window(start: str, end: str) -> TimeWindow:
    return TimeWindow(datetime.fromisoformat(start), datetime.fromisoformat(end))


def _registration(session: Session) -> ConnectorRegistrationService:
    settings = get_settings()
    if not settings.credentials_key:
        raise CredentialCipherError(
            "YIELDFIELD_CREDENTIALS_KEY is required to use connectors (§16)."
        )
    return ConnectorRegistrationService(
        SqlAlchemyConnectorRepository(session),
        FernetCredentialCipher(settings.credentials_key),
        base_url=settings.connector_base_url,
    )


def _require_ingestion_enabled() -> None:
    if not get_settings().ingestion_enabled:
        raise RuntimeError("Ingestion is disabled (YIELDFIELD_INGESTION_ENABLED).")


@celery_app.task(name="yieldfield.run_reconciliation", bind=True)  # type: ignore[untyped-decorator]  # Celery decorator is untyped
def run_reconciliation_task(
    self: Any, job_id: str, tenant_id: str, start: str, end: str, reconciliation_id: str
) -> None:
    tenant = TenantId(tenant_id)
    with _session_factory()() as session:

        def work() -> JobResult:
            use_case = RunReconciliation(
                SqlAlchemyInvoiceRepository(session),
                _usage_event_store(),
                SqlAlchemyContractRepository(session),
                SqlAlchemyPlanRepository(session),
                SqlAlchemyReconciliationRepository(session),
            )
            reconciliation = use_case.run(
                tenant, _window(start, end), ReconciliationId(reconciliation_id)
            )
            _log.info(
                "reconciliation.completed",
                tenant_id=tenant_id,
                job_id=job_id,
                reconciliation_id=reconciliation_id,
                finding_count=reconciliation.finding_count,
            )
            return (JobResultType.RECONCILIATION, str(reconciliation.id))

        run_as_job(
            jobs=SqlAlchemyJobRepository(session),
            commit=session.commit,
            rollback=session.rollback,
            tenant_id=tenant,
            job_id=job_id,
            work=work,
            celery_task_id=self.request.id,
        )


@celery_app.task(name="yieldfield.ingest_invoices", bind=True)  # type: ignore[untyped-decorator]  # Celery decorator is untyped
def ingest_invoices_task(
    self: Any, job_id: str, tenant_id: str, start: str, end: str, connector_id: str
) -> None:
    tenant = TenantId(tenant_id)
    with _session_factory()() as session:

        def work() -> None:
            _require_ingestion_enabled()
            connector = _registration(session).build_authenticated(
                tenant, ConnectorId(connector_id)
            )
            count = IngestInvoices(SqlAlchemyInvoiceRepository(session)).run(
                tenant, _window(start, end), connector
            )
            _log.info(
                "ingestion.invoices_completed",
                tenant_id=tenant_id,
                job_id=job_id,
                connector_id=connector_id,
                count=count,
            )

        run_as_job(
            jobs=SqlAlchemyJobRepository(session),
            commit=session.commit,
            rollback=session.rollback,
            tenant_id=tenant,
            job_id=job_id,
            work=work,
            celery_task_id=self.request.id,
        )


@celery_app.task(name="yieldfield.ingest_usage_events", bind=True)  # type: ignore[untyped-decorator]  # Celery decorator is untyped
def ingest_usage_events_task(
    self: Any, job_id: str, tenant_id: str, start: str, end: str, connector_id: str
) -> None:
    tenant = TenantId(tenant_id)
    with _session_factory()() as session:

        def work() -> None:
            _require_ingestion_enabled()
            connector = _registration(session).build_authenticated(
                tenant, ConnectorId(connector_id)
            )
            count = IngestUsageEvents(_usage_event_store()).run(
                tenant, _window(start, end), connector
            )
            _log.info(
                "ingestion.usage_events_completed",
                tenant_id=tenant_id,
                job_id=job_id,
                connector_id=connector_id,
                count=count,
            )

        run_as_job(
            jobs=SqlAlchemyJobRepository(session),
            commit=session.commit,
            rollback=session.rollback,
            tenant_id=tenant,
            job_id=job_id,
            work=work,
            celery_task_id=self.request.id,
        )
