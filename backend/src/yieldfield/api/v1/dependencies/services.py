"""Composition of 3A adapters for request handling (spec §5.1) — the only place API code
builds repositories, the cipher, or the registration service. Routers consume the
Annotated aliases and never import infrastructure themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Depends
from sqlalchemy.orm import Session

from yieldfield.api.v1.dependencies.database import DbSession
from yieldfield.api.v1.dependencies.settings import SettingsDep
from yieldfield.api.v1.dependencies.tasks import TaskQueue, TaskQueueDep
from yieldfield.api.v1.schemas.jobs import JobStatusRead
from yieldfield.config.settings import Settings
from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.connectors.registration import ConnectorRegistrationService
from yieldfield.infrastructure.persistence.job import Job, JobStatus, JobType
from yieldfield.infrastructure.persistence.repositories import (
    SqlAlchemyConnectorRepository,
    SqlAlchemyFindingRepository,
    SqlAlchemyJobRepository,
    SqlAlchemyReconciliationRepository,
)
from yieldfield.infrastructure.security.credential_cipher import (
    CredentialCipherError,
    FernetCredentialCipher,
)


def get_job_repository(session: DbSession) -> SqlAlchemyJobRepository:
    return SqlAlchemyJobRepository(session)


def get_connector_store(session: DbSession) -> SqlAlchemyConnectorRepository:
    return SqlAlchemyConnectorRepository(session)


def get_finding_repository(session: DbSession) -> SqlAlchemyFindingRepository:
    return SqlAlchemyFindingRepository(session)


def get_reconciliation_repository(session: DbSession) -> SqlAlchemyReconciliationRepository:
    return SqlAlchemyReconciliationRepository(session)


def _cipher(settings: Settings) -> FernetCredentialCipher:
    if not settings.credentials_key:
        raise CredentialCipherError(
            "YIELDFIELD_CREDENTIALS_KEY is required to register or use connectors (§16)."
        )
    return FernetCredentialCipher(settings.credentials_key)


def get_registration_service(
    session: DbSession, settings: SettingsDep
) -> ConnectorRegistrationService:
    return ConnectorRegistrationService(
        SqlAlchemyConnectorRepository(session),
        _cipher(settings),
        base_url=settings.connector_base_url,
    )


JobRepo = Annotated[SqlAlchemyJobRepository, Depends(get_job_repository)]
ConnectorStoreDep = Annotated[SqlAlchemyConnectorRepository, Depends(get_connector_store)]
FindingRepo = Annotated[SqlAlchemyFindingRepository, Depends(get_finding_repository)]
ReconciliationRepo = Annotated[
    SqlAlchemyReconciliationRepository, Depends(get_reconciliation_repository)
]
RegistrationDep = Annotated[ConnectorRegistrationService, Depends(get_registration_service)]


def job_status_read(job: Job) -> JobStatusRead:
    """Map the infrastructure Job onto the DTO here so routers never import infrastructure."""
    return JobStatusRead(
        job_id=job.id,
        job_type=job.job_type.value,
        status=job.status.value,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
        result_type=job.result_type.value if job.result_type is not None else None,
        result_ref=job.result_ref,
    )


# Task names are the API↔worker contract: the API enqueues by name (never imports task
# functions), the worker registers tasks under exactly these names (spec §7).
INGEST_INVOICES_TASK = "yieldfield.ingest_invoices"
INGEST_USAGE_EVENTS_TASK = "yieldfield.ingest_usage_events"
RUN_RECONCILIATION_TASK = "yieldfield.run_reconciliation"

_JOB_TYPE_BY_TASK: dict[str, JobType] = {
    INGEST_INVOICES_TASK: JobType.INGEST_INVOICES,
    INGEST_USAGE_EVENTS_TASK: JobType.INGEST_USAGE_EVENTS,
    RUN_RECONCILIATION_TASK: JobType.RUN_RECONCILIATION,
}


@dataclass(frozen=True, slots=True)
class JobSubmitter:
    """Create the PENDING Job, COMMIT it, then enqueue — in that order (§3).

    The commit-before-enqueue ordering is load-bearing: with `task_acks_late` a fast worker
    can pick the task up immediately, and `run_as_job` must find the Job row. Worker args
    convention: (job_id, tenant_id, *task_args), all strings (JSON-serializable).

    The broker task id is deliberately not captured here: the worker records its own
    `self.request.id` when `run_as_job` marks the Job RUNNING (§3). If enqueue fails after
    the commit, the row stays durably PENDING (visible via GET /jobs/{id}) with no worker
    behind it; sweeping such orphans is out of scope this slice.
    """

    session: Session
    jobs: SqlAlchemyJobRepository
    queue: TaskQueue

    def submit(self, tenant_id: TenantId, task_name: str, *task_args: str) -> str:
        job_id = f"job_{uuid4()}"
        self.jobs.add(
            tenant_id,
            Job(
                id=job_id,
                tenant_id=tenant_id,
                job_type=_JOB_TYPE_BY_TASK[task_name],
                status=JobStatus.PENDING,
                created_at=datetime.now(UTC),
            ),
        )
        self.session.commit()
        self.queue.enqueue(task_name, job_id, str(tenant_id), *task_args)
        return job_id


def get_job_submitter(session: DbSession, queue: TaskQueueDep) -> JobSubmitter:
    return JobSubmitter(session, SqlAlchemyJobRepository(session), queue)


JobSubmitterDep = Annotated[JobSubmitter, Depends(get_job_submitter)]
